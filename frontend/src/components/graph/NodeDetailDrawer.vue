<script setup lang="ts">
import { computed, ref, watch, h } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'
import type { CharacterMemory } from '@/api/memories'
import { updateCharacter, deleteCharacter } from '@/api/characters'
import { parseApiError } from '@/utils/apiError'
import { useCharacterMemories } from '@/composables/useCharacterMemories'
import MarkdownText from '@/components/common/MarkdownText.vue'
import {
  NDrawer,
  NDrawerContent,
  NTag,
  NEmpty,
  NButton,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NPopconfirm,
  NTabs,
  NTabPane,
  useMessage,
} from 'naive-ui'

const props = defineProps<{
  visible: boolean
  worldId: string
  character: Character | null
  characters: Character[]
  relations: Relation[]
}>()

const emit = defineEmits<{
  'update:visible': [v: boolean]
  'character-updated': [c: Character]
  'character-deleted': [id: string]
}>()

const { t } = useI18n()
const messageApi = useMessage()

const editing = ref(false)
const saving = ref(false)
const deleting = ref(false)
const editName = ref('')
const editBrief = ref('')
const editDetail = ref('')
const editPersonality = ref('')
const editSpeechStyle = ref('')
const editTier = ref<string>('supporting')

// 记忆 Tab
const activeTab = ref<string>('profile')
const memorySubTab = ref<string>('short')

// Memory CRUD via composable
const characterId = computed(() => props.character?.id ?? null)
const charactersRef = computed(() => props.characters)
const {
  shortTermMemories,
  longTermMemories,
  memoriesLoading,
  eventNameOptions,
  creatingMemory,
  createForm,
  editingMemoryId,
  editForm,
  editSaving,
  createSaving,
  categoryOptions,
  characterOptions,
  loadMemories,
  loadEventNames,
  startCreate: _startCreate,
  saveNewMemory,
  startEditMemory,
  cancelEditMemory,
  saveEditMemory,
  onDeleteMemory,
  resetCreateForm,
} = useCharacterMemories(props.worldId, characterId, messageApi, charactersRef)

const tierSaving = ref(false)

async function changeTier(newTier: string) {
  if (!props.character || tierSaving.value || props.character.tier === newTier) return
  tierSaving.value = true
  try {
    const updated = await updateCharacter(props.worldId, props.character.id, { tier: newTier })
    emit('character-updated', updated)
  } catch {
    messageApi.error(t('character.tierUpdateFailed'))
  } finally {
    tierSaving.value = false
  }
}

const TIER_ORDER: Record<string, number> = { core: 0, supporting: 1, extra: 2 }

const sortedCharacterOptions = computed(() => {
  const currentId = props.character?.id
  if (!currentId) return characterOptions.value
  const relatedIds = new Set<string>()
  for (const r of props.relations) {
    if (r.character_a === currentId) relatedIds.add(r.character_b)
    if (r.character_b === currentId) relatedIds.add(r.character_a)
  }
  return [...characterOptions.value]
    .filter(o => o.value !== currentId)
    .sort((a, b) => {
      const aRel = relatedIds.has(a.value) ? 0 : 1
      const bRel = relatedIds.has(b.value) ? 0 : 1
      if (aRel !== bRel) return aRel - bRel
      return (TIER_ORDER[a.tier ?? ''] ?? 3) - (TIER_ORDER[b.tier ?? ''] ?? 3)
    })
})

watch(activeTab, async (tab) => {
  if (tab === 'memories' && props.character) {
    await Promise.all([loadMemories(), loadEventNames()])
  }
})

watch(
  () => props.character,
  () => {
    activeTab.value = 'profile'
  },
)

function startCreate() {
  _startCreate(memorySubTab.value === 'short' ? 'short_term' : 'long_term')
}

const categoryTagType = (cat: string | null | undefined): 'default' | 'warning' | 'error' => {
  if (cat === 'major') return 'error'
  if (cat === 'private') return 'warning'
  return 'default'
}

const categoryLabel = (cat: string | null | undefined): string => {
  const map: Record<string, string> = {
    trivial: t('character.memoryCategoryTrivial'),
    private: t('character.memoryCategoryPrivate'),
    major: t('character.memoryCategoryMajor'),
  }
  return map[cat ?? ''] ?? cat ?? ''
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return dateStr
  }
}

function characterName(id: string): string {
  return props.characters.find(c => c.id === id)?.name ?? id
}

function renderInvolvedTag({
  option,
  handleClose,
}: {
  option: Record<string, unknown>
  handleClose: () => void
}) {
  const count = editForm.value.involved_characters?.length
    ?? createForm.value.involved_characters?.length
    ?? 0
  const label = count <= 1
    ? String(option.label ?? '')
    : `${String(option.label ?? '')} +${count - 1}`
  return h(
    NTag,
    { size: 'small', closable: true, onClose: handleClose },
    { default: () => label },
  )
}

const tierOptions = computed(() => [
  { label: t('graph.tierCore'), value: 'core' },
  { label: t('graph.tierSupporting'), value: 'supporting' },
  { label: t('graph.tierExtra'), value: 'extra' },
])

// 头像上传
const uploading = ref(false)
const clearingAvatar = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

function onAvatarClick() {
  fileInputRef.value?.click()
}

async function onClearAvatar() {
  if (!props.character || clearingAvatar.value) return
  clearingAvatar.value = true
  try {
    const updated = await updateCharacter(props.worldId, props.character.id, {
      portrait_url: null,
    })
    emit('character-updated', updated)
    messageApi.success(t('character.avatarCleared'))
  } catch {
    messageApi.error(t('character.uploadFailed'))
  } finally {
    clearingAvatar.value = false
  }
}

async function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !props.character) return
  if (!file.type.startsWith('image/')) {
    messageApi.error(t('character.invalidFileType'))
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    messageApi.error(t('character.fileTooLarge'))
    return
  }

  uploading.value = true
  try {
    const base64 = await fileToBase64(file)
    const updated = await updateCharacter(props.worldId, props.character.id, {
      portrait_url: base64,
    })
    emit('character-updated', updated)
    messageApi.success(t('character.avatarUpdated'))
  } catch {
    messageApi.error(t('character.uploadFailed'))
  } finally {
    uploading.value = false
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

watch(
  () => props.character,
  (c) => {
    if (c) {
      editName.value = c.name
      editBrief.value = c.profile.brief ?? ''
      editDetail.value = c.profile.detail ?? ''
      editPersonality.value = c.profile.personality ?? ''
      editSpeechStyle.value = c.profile.speech_style ?? ''
      editTier.value = c.tier ?? 'supporting'
    }
    editing.value = false
  },
)

function startEdit() {
  if (!props.character) return
  editName.value = props.character.name
  editBrief.value = props.character.profile.brief ?? ''
  editDetail.value = props.character.profile.detail ?? ''
  editPersonality.value = props.character.profile.personality ?? ''
  editSpeechStyle.value = props.character.profile.speech_style ?? ''
  editTier.value = props.character.tier ?? 'supporting'
  editing.value = true
}

async function saveEdit() {
  if (!props.character) return
  saving.value = true
  try {
    const updated = await updateCharacter(props.worldId, props.character.id, {
      name: editName.value || undefined,
      tier: editTier.value,
      profile: {
        ...props.character.profile,
        brief: editBrief.value || undefined,
        detail: editDetail.value || undefined,
        personality: editPersonality.value || undefined,
        speech_style: editSpeechStyle.value || undefined,
      },
    })
    emit('character-updated', updated)
    editing.value = false
  } finally {
    saving.value = false
  }
}

async function onDeleteCharacter() {
  if (!props.character || deleting.value) return
  deleting.value = true
  try {
    await deleteCharacter(props.worldId, props.character.id)
    messageApi.success(t('character.deleted'))
    emit('character-deleted', props.character.id)
    emit('update:visible', false)
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    deleting.value = false
  }
}

</script>

<template>
  <NDrawer
    :show="visible"
    :width="420"
    @update:show="(v: boolean) => emit('update:visible', v)"
  >
    <NDrawerContent v-if="character" closable>
      <div class="node-drawer">
          <!-- Hero 区域 (固定) -->
          <div class="node-drawer__hero">
            <NPopconfirm @positive-click="onDeleteCharacter">
              <template #trigger>
                <NButton
                  class="node-drawer__delete-btn"
                  size="tiny"
                  quaternary
                  type="error"
                  :loading="deleting"
                >{{ $t('character.deleteButton') }}</NButton>
              </template>
              {{ $t('character.deleteConfirm', { name: character.name }) }}
            </NPopconfirm>
            <div class="node-drawer__avatar-wrap">
              <div
                class="node-drawer__avatar"
                :class="{ 'node-drawer__avatar--uploading': uploading }"
                :title="$t('character.uploadAvatar')"
                @click="onAvatarClick"
              >
                <img v-if="character.portrait_url" :src="character.portrait_url" class="node-drawer__avatar-img" />
                <span v-else class="node-drawer__avatar-initial">{{ character.name.charAt(0) }}</span>
                <div class="node-drawer__avatar-overlay">
                  <span>{{ uploading ? '...' : '📷' }}</span>
                </div>
              </div>
              <button
                v-if="character.portrait_url"
                class="node-drawer__avatar-clear"
                :title="$t('character.clearAvatar')"
                @click.stop="onClearAvatar"
              >&times;</button>
            </div>
            <div class="node-drawer__name">{{ character.name }}</div>
            <input
              ref="fileInputRef"
              type="file"
              accept="image/*"
              style="display: none"
              @change="onFileChange"
            />
            <div class="node-drawer__tags">
              <NTag v-if="character.entity_type && character.entity_type !== 'character'" size="small" round :bordered="false" type="warning">{{ character.entity_type }}</NTag>
            </div>
            <div class="node-drawer__tier-switch" :class="{ 'node-drawer__tier-switch--disabled': tierSaving }">
              <button
                v-for="opt in tierOptions"
                :key="opt.value"
                class="node-drawer__tier-btn"
                :class="{
                  'node-drawer__tier-btn--active': (character.tier ?? 'supporting') === opt.value,
                  'node-drawer__tier-btn--core': opt.value === 'core',
                  'node-drawer__tier-btn--supporting': opt.value === 'supporting',
                  'node-drawer__tier-btn--extra': opt.value === 'extra',
                }"
                :disabled="tierSaving"
                :title="opt.label"
                @click="changeTier(opt.value)"
              >{{ opt.label }}</button>
            </div>
          </div>

          <div class="node-drawer__divider" />

          <!-- Tab 栏 (固定) -->
          <div class="node-drawer__tab-bar">
            <button
              class="node-drawer__tab-btn"
              :class="{ 'node-drawer__tab-btn--active': activeTab === 'profile' }"
              @click="activeTab = 'profile'"
            >{{ $t('character.tabProfile') }}</button>
            <button
              class="node-drawer__tab-btn"
              :class="{ 'node-drawer__tab-btn--active': activeTab === 'memories' }"
              @click="activeTab = 'memories'"
            >{{ $t('character.tabMemories') }}</button>
            <div class="node-drawer__tab-actions">
              <NButton
                v-if="activeTab === 'profile' && !editing"
                size="tiny"
                quaternary
                @click="startEdit"
              >{{ $t('common.edit') }}</NButton>
              <NButton
                v-if="activeTab === 'memories'"
                size="tiny"
                quaternary
                :disabled="creatingMemory"
                @click="startCreate"
              >+ {{ memorySubTab === 'short' ? $t('character.memoryCreateShort') : $t('character.memoryCreateLong') }}</NButton>
            </div>
          </div>

          <!-- 可滚动内容区 -->
          <div class="node-drawer__scroll">
            <!-- 档案内容 -->
            <div v-show="activeTab === 'profile'" class="node-drawer__panel">
              <!-- 查看态 -->
              <template v-if="!editing">
                <div class="node-drawer__content">
                  <div v-if="character.profile.brief" class="node-drawer__section">
                    <div class="node-drawer__label">{{ $t('character.brief') }}</div>
                    <MarkdownText class="node-drawer__brief" :text="character.profile.brief" />
                  </div>

                  <div v-if="character.profile.detail" class="node-drawer__section">
                    <div class="node-drawer__label">{{ $t('character.detailLabel') }}</div>
                    <MarkdownText class="node-drawer__detail" :text="character.profile.detail" />
                  </div>

                  <div class="node-drawer__section">
                    <div class="node-drawer__label">{{ $t('character.personality') }}</div>
                    <MarkdownText
                      v-if="character.profile.personality"
                      class="node-drawer__detail"
                      :text="character.profile.personality"
                    />
                    <div v-else class="node-drawer__detail node-drawer__detail--empty">{{ $t('common.empty') }}</div>
                  </div>

                  <div class="node-drawer__section">
                    <div class="node-drawer__label">{{ $t('character.speechStyle') }}</div>
                    <MarkdownText
                      v-if="character.profile.speech_style"
                      class="node-drawer__detail"
                      :text="character.profile.speech_style"
                    />
                    <div v-else class="node-drawer__detail node-drawer__detail--empty">{{ $t('common.empty') }}</div>
                  </div>

                  <NEmpty
                    v-if="!character.profile.brief && !character.profile.detail && !character.profile.personality && !character.profile.speech_style"
                    :description="$t('graph.noDetail')"
                    class="node-drawer__empty"
                  />
                </div>
              </template>

              <!-- 编辑态 -->
              <template v-else>
                <div class="node-drawer__content">
                  <div class="node-drawer__edit-form">
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.nameLabel') }}</label>
                      <NInput v-model:value="editName" :placeholder="$t('character.namePlaceholder')" />
                    </div>
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.tierLabel') }}</label>
                      <NSelect v-model:value="editTier" :options="tierOptions" />
                    </div>
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.brief') }}</label>
                      <NInput
                        v-model:value="editBrief"
                        type="textarea"
                        :placeholder="$t('character.briefPlaceholder')"
                        :autosize="{ minRows: 2, maxRows: 4 }"
                      />
                    </div>
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.detailLabel') }}</label>
                      <NInput
                        v-model:value="editDetail"
                        type="textarea"
                        :placeholder="$t('character.detailPlaceholder')"
                        :autosize="{ minRows: 4, maxRows: 10 }"
                      />
                    </div>
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.personality') }}</label>
                      <NInput
                        v-model:value="editPersonality"
                        type="textarea"
                        :placeholder="$t('character.personalityPlaceholder')"
                        :autosize="{ minRows: 2, maxRows: 6 }"
                      />
                    </div>
                    <div class="node-drawer__field">
                      <label class="node-drawer__field-label">{{ $t('character.speechStyle') }}</label>
                      <NInput
                        v-model:value="editSpeechStyle"
                        type="textarea"
                        :placeholder="$t('character.speechStylePlaceholder')"
                        :autosize="{ minRows: 2, maxRows: 6 }"
                      />
                    </div>
                  </div>
                  <NSpace class="node-drawer__edit-actions">
                    <NButton type="primary" :loading="saving" @click="saveEdit">{{ $t('common.save') }}</NButton>
                    <NButton :disabled="saving" @click="editing = false">{{ $t('common.cancel') }}</NButton>
                  </NSpace>
                </div>
              </template>
            </div>

            <!-- 记忆内容 -->
            <div v-show="activeTab === 'memories'" class="node-drawer__panel">
              <NSpin :show="memoriesLoading">
                <NTabs v-model:value="memorySubTab" type="line" class="node-drawer__sub-tabs">
                  <!-- 短期记忆子 Tab -->
                  <NTabPane name="short" :tab="$t('character.shortTermMemories')">
                    <div class="node-drawer__content">
                      <!-- 新建表单 -->
                      <div v-if="creatingMemory" class="node-drawer__memory-form">
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryContentPlaceholder') }}</label>
                          <NInput
                            v-model:value="createForm.content"
                            type="textarea"
                            :autosize="{ minRows: 2, maxRows: 6 }"
                          />
                        </div>
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryCategoryLabel') }}</label>
                          <NSelect
                            v-model:value="createForm.memory_category"
                            :options="categoryOptions"
                            clearable
                          />
                        </div>
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryReflection') }}</label>
                          <NInput
                            v-model:value="createForm.short_term_reflection"
                            type="textarea"
                            :autosize="{ minRows: 1, maxRows: 3 }"
                          />
                        </div>
                        <NSpace class="node-drawer__edit-actions">
                          <NButton type="primary" size="small" :loading="createSaving" :disabled="!createForm.content.trim()" @click="saveNewMemory">{{ $t('common.save') }}</NButton>
                          <NButton size="small" :disabled="createSaving" @click="resetCreateForm">{{ $t('common.cancel') }}</NButton>
                        </NSpace>
                      </div>

                      <!-- 记忆卡片列表 -->
                      <template v-if="!creatingMemory || shortTermMemories.length > 0">
                        <div v-if="shortTermMemories.length > 0" class="node-drawer__memories">
                          <div
                            v-for="mem in shortTermMemories"
                            :key="mem.id"
                            class="node-drawer__memory-card"
                          >
                            <!-- 编辑模式 -->
                            <template v-if="editingMemoryId === mem.id">
                              <div class="node-drawer__memory-edit-form">
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryContentPlaceholder') }}</label>
                                  <NInput
                                    v-model:value="editForm.content"
                                    type="textarea"
                                    :autosize="{ minRows: 2, maxRows: 6 }"
                                  />
                                </div>
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryCategoryLabel') }}</label>
                                  <NSelect
                                    v-model:value="editForm.memory_category"
                                    :options="categoryOptions"
                                    clearable
                                  />
                                </div>
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryReflection') }}</label>
                                  <NInput
                                    v-model:value="editForm.short_term_reflection"
                                    type="textarea"
                                    :autosize="{ minRows: 1, maxRows: 3 }"
                                  />
                                </div>
                                <NSpace class="node-drawer__edit-actions">
                                  <NButton type="primary" size="tiny" :loading="editSaving" @click="saveEditMemory(mem)">{{ $t('common.save') }}</NButton>
                                  <NButton size="tiny" :disabled="editSaving" @click="cancelEditMemory">{{ $t('common.cancel') }}</NButton>
                                </NSpace>
                              </div>
                            </template>

                            <!-- 只读模式 -->
                            <template v-else>
                              <div class="node-drawer__memory-header">
                                <NTag
                                  v-if="mem.memory_category"
                                  size="tiny"
                                  :type="categoryTagType(mem.memory_category)"
                                  :bordered="false"
                                >
                                  {{ categoryLabel(mem.memory_category) }}
                                </NTag>
                                <span class="node-drawer__memory-date">{{ formatDate(mem.created_at) }}</span>
                                <NButton size="tiny" quaternary class="node-drawer__memory-edit-btn" @click="startEditMemory(mem)">
                                  &#9998;
                                </NButton>
                                <NPopconfirm @positive-click="onDeleteMemory(mem.id)">
                                  <template #trigger>
                                    <NButton size="tiny" quaternary type="error" class="node-drawer__memory-delete">
                                      &times;
                                    </NButton>
                                  </template>
                                  {{ $t('character.memoryDeleteConfirm') }}
                                </NPopconfirm>
                              </div>
                              <div class="node-drawer__memory-content">{{ mem.content }}</div>
                              <div v-if="mem.short_term_reflection" class="node-drawer__memory-reflection">
                                {{ mem.short_term_reflection }}
                              </div>
                            </template>
                          </div>
                        </div>

                        <NEmpty
                          v-else-if="!creatingMemory"
                          :description="$t('character.noMemories')"
                          class="node-drawer__empty"
                        />
                      </template>
                    </div>
                  </NTabPane>

                  <!-- 长期记忆子 Tab -->
                  <NTabPane name="long" :tab="$t('character.longTermMemories')">
                    <div class="node-drawer__content">
                      <!-- 新建表单 -->
                      <div v-if="creatingMemory" class="node-drawer__memory-form">
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryEventNameLabel') }} *</label>
                          <NSelect
                            v-model:value="createForm.event_name"
                            :options="eventNameOptions"
                            filterable
                            tag
                            :placeholder="$t('character.memoryEventNameLabel')"
                          />
                        </div>
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryPerspective') }} *</label>
                          <NInput
                            v-model:value="createForm.perspective_detail"
                            type="textarea"
                            :autosize="{ minRows: 2, maxRows: 6 }"
                          />
                        </div>
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryReflection') }}</label>
                          <NInput
                            v-model:value="createForm.reflection"
                            type="textarea"
                            :autosize="{ minRows: 1, maxRows: 3 }"
                          />
                        </div>
                        <div class="node-drawer__field">
                          <label class="node-drawer__field-label">{{ $t('character.memoryInvolvedCharacters') }}</label>
                          <NSelect
                            v-model:value="createForm.involved_characters"
                            :options="sortedCharacterOptions"
                            multiple
                            filterable
                            :max-tag-count="1"
                            :render-tag="renderInvolvedTag"
                            :placeholder="$t('character.memoryInvolvedCharactersPlaceholder')"
                          />
                        </div>
                        <NSpace class="node-drawer__edit-actions">
                          <NButton type="primary" size="small" :loading="createSaving" :disabled="!createForm.event_name?.trim() || !createForm.perspective_detail?.trim()" @click="saveNewMemory">{{ $t('common.save') }}</NButton>
                          <NButton size="small" :disabled="createSaving" @click="resetCreateForm">{{ $t('common.cancel') }}</NButton>
                        </NSpace>
                      </div>

                      <!-- 记忆卡片列表 -->
                      <template v-if="!creatingMemory || longTermMemories.length > 0">
                        <div v-if="longTermMemories.length > 0" class="node-drawer__memories">
                          <div
                            v-for="mem in longTermMemories"
                            :key="mem.id"
                            class="node-drawer__memory-card"
                          >
                            <!-- 编辑模式 -->
                            <template v-if="editingMemoryId === mem.id">
                              <div class="node-drawer__memory-edit-form">
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryEventNameLabel') }}</label>
                                  <NSelect
                                    v-model:value="editForm.event_name"
                                    :options="eventNameOptions"
                                    filterable
                                    tag
                                    :placeholder="$t('character.memoryEventNameLabel')"
                                  />
                                </div>
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryPerspective') }}</label>
                                  <NInput
                                    v-model:value="editForm.perspective_detail"
                                    type="textarea"
                                    :autosize="{ minRows: 2, maxRows: 6 }"
                                  />
                                </div>
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryReflection') }}</label>
                                  <NInput
                                    v-model:value="editForm.reflection"
                                    type="textarea"
                                    :autosize="{ minRows: 1, maxRows: 3 }"
                                  />
                                </div>
                                <div class="node-drawer__field">
                                  <label class="node-drawer__field-label">{{ $t('character.memoryInvolvedCharacters') }}</label>
                                  <NSelect
                                    v-model:value="editForm.involved_characters"
                                    :options="sortedCharacterOptions"
                                    multiple
                                    filterable
                                    :max-tag-count="1"
                                    :render-tag="renderInvolvedTag"
                                    :placeholder="$t('character.memoryInvolvedCharactersPlaceholder')"
                                  />
                                </div>
                                <NSpace class="node-drawer__edit-actions">
                                  <NButton type="primary" size="tiny" :loading="editSaving" @click="saveEditMemory(mem)">{{ $t('common.save') }}</NButton>
                                  <NButton size="tiny" :disabled="editSaving" @click="cancelEditMemory">{{ $t('common.cancel') }}</NButton>
                                </NSpace>
                              </div>
                            </template>

                            <!-- 只读模式 -->
                            <template v-else>
                              <div class="node-drawer__memory-header">
                                <span v-if="mem.event_name" class="node-drawer__memory-event">{{ mem.event_name }}</span>
                                <span class="node-drawer__memory-date">{{ formatDate(mem.created_at) }}</span>
                                <NButton size="tiny" quaternary class="node-drawer__memory-edit-btn" @click="startEditMemory(mem)">
                                  &#9998;
                                </NButton>
                                <NPopconfirm @positive-click="onDeleteMemory(mem.id)">
                                  <template #trigger>
                                    <NButton size="tiny" quaternary type="error" class="node-drawer__memory-delete">
                                      &times;
                                    </NButton>
                                  </template>
                                  {{ $t('character.memoryDeleteConfirm') }}
                                </NPopconfirm>
                              </div>
                              <div class="node-drawer__memory-content">{{ mem.content }}</div>
                              <div v-if="mem.perspective_detail" class="node-drawer__memory-detail">
                                {{ mem.perspective_detail }}
                              </div>
                              <div v-if="mem.reflection" class="node-drawer__memory-reflection">
                                {{ mem.reflection }}
                              </div>
                              <div v-if="mem.involved_characters?.length" class="node-drawer__memory-involved">
                                <span class="node-drawer__field-label">{{ $t('character.memoryInvolvedCharacters') }}:</span>
                                <NTag v-for="cid in mem.involved_characters" :key="cid" size="small" class="node-drawer__memory-involved-tag">
                                  {{ characterName(cid) }}
                                </NTag>
                              </div>
                            </template>
                          </div>
                        </div>

                        <NEmpty
                          v-else-if="!creatingMemory"
                          :description="$t('character.noMemories')"
                          class="node-drawer__empty"
                        />
                      </template>
                    </div>
                  </NTabPane>
                </NTabs>
              </NSpin>
            </div>
        </div>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.node-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* 打通 Naive UI 内部 flex 链，让高度约束传递到 .node-drawer */
:deep(.n-drawer-body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden !important;
}

:deep(.n-drawer-body-content-wrapper) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Hero (固定) */
.node-drawer__hero {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacing-lg) var(--spacing-lg) var(--spacing-md);
  text-align: center;
  flex-shrink: 0;
}

.node-drawer__delete-btn {
  position: absolute;
  top: var(--spacing-sm);
  left: var(--spacing-sm);
}

.node-drawer__avatar-wrap {
  position: relative;
  width: 80px;
  height: 80px;
  flex-shrink: 0;
  margin-bottom: var(--spacing-sm);
}

.node-drawer__avatar-wrap:hover .node-drawer__avatar-clear {
  opacity: 1;
}

.node-drawer__avatar {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-deep);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 32px;
  font-family: var(--font-display);
  overflow: hidden;
  position: relative;
  cursor: pointer;
  box-shadow: 0 0 0 3px var(--bg-deep), 0 0 0 4px var(--accent-dim), 0 4px 20px var(--accent-glow);
  transition: box-shadow 0.3s ease;
}

.node-drawer__avatar:hover {
  box-shadow: 0 0 0 3px var(--bg-deep), 0 0 0 4px var(--accent), 0 4px 24px var(--accent-glow);
}

.node-drawer__avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.node-drawer__avatar-initial {
  font-size: 32px;
}

.node-drawer__avatar-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s;
  font-size: 20px;
  border-radius: 50%;
}

.node-drawer__avatar:hover .node-drawer__avatar-overlay,
.node-drawer__avatar--uploading .node-drawer__avatar-overlay {
  opacity: 1;
}

.node-drawer__avatar-clear {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s, color 0.2s;
  padding: 0;
}

.node-drawer__avatar-clear:hover {
  color: var(--text-primary);
}

.node-drawer__name {
  margin: 0;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  margin-bottom: var(--spacing-xs);
}

.node-drawer__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
}

/* Tier 快捷切换 */
.node-drawer__tier-switch {
  display: flex;
  gap: 4px;
  margin-top: 6px;
}

.node-drawer__tier-switch--disabled {
  opacity: 0.6;
  pointer-events: none;
}

.node-drawer__tier-btn {
  padding: 2px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}

.node-drawer__tier-btn:hover {
  border-color: var(--text-muted);
  color: var(--text-primary);
}

.node-drawer__tier-btn--active.node-drawer__tier-btn--core {
  background: rgba(208, 48, 48, 0.15);
  border-color: #d03030;
  color: #d03030;
  font-weight: 600;
}

.node-drawer__tier-btn--active.node-drawer__tier-btn--supporting {
  background: rgba(200, 150, 30, 0.15);
  border-color: #c8961e;
  color: #c8961e;
  font-weight: 600;
}

.node-drawer__tier-btn--active.node-drawer__tier-btn--extra {
  background: var(--bg-card);
  border-color: var(--text-muted);
  color: var(--text-primary);
  font-weight: 600;
}

/* 可滚动内容区 */
.node-drawer__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 内容面板 */
.node-drawer__panel {
  padding: 0 var(--spacing-lg);
}

/* 分割线 */
.node-drawer__divider {
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, var(--accent-dim) 20%, var(--accent) 50%, var(--accent-dim) 80%, transparent 100%);
  opacity: 0.4;
  margin: 0 var(--spacing-lg);
  flex-shrink: 0;
}

/* Tab 栏 (固定) */
.node-drawer__tab-bar {
  display: flex;
  align-items: center;
  position: relative;
  padding: 0 var(--spacing-lg);
  padding-right: calc(var(--spacing-lg) + 90px);
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}

.node-drawer__tab-btn {
  flex: 1;
  background: none;
  border: none;
  padding: 10px 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  position: relative;
  transition: color 0.2s;
}

.node-drawer__tab-btn:hover {
  color: var(--text-primary);
}

.node-drawer__tab-btn--active {
  color: var(--accent);
}

.node-drawer__tab-btn--active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 20%;
  right: 20%;
  height: 2px;
  background: var(--accent);
  border-radius: 1px;
}

.node-drawer__tab-actions {
  position: absolute;
  right: var(--spacing-lg);
  top: 50%;
  transform: translateY(-50%);
  min-width: 90px;
  display: flex;
  justify-content: flex-end;
  white-space: nowrap;
}

/* 子 Tabs */
.node-drawer__sub-tabs :deep(.n-tabs-tab) {
  flex: 1 !important;
  justify-content: center !important;
  width: 50% !important;
  font-size: 12px;
  font-weight: 600;
}

/* 内容区 */
.node-drawer__content {
  padding: var(--spacing-md) 0 var(--spacing-lg);
}

.node-drawer__section {
  margin-bottom: var(--spacing-md);
}

.node-drawer__label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: var(--spacing-xs);
}

.node-drawer__brief {
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.7;
}

.node-drawer__detail {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
  white-space: pre-wrap;
}

.node-drawer__detail--empty {
  color: var(--text-muted);
  font-style: italic;
}

.node-drawer__empty {
  padding: var(--spacing-xl) 0;
}

/* 编辑态 */
.node-drawer__edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.node-drawer__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.node-drawer__field-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}

.node-drawer__edit-actions {
  margin-top: 12px;
  justify-content: flex-end;
}

/* 记忆新建/编辑表单 */
.node-drawer__memory-form,
.node-drawer__memory-edit-form {
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-dim);
  padding: 12px;
  margin-bottom: var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

/* 记忆卡片 */
.node-drawer__memories {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.node-drawer__memory-card {
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  padding: 10px 12px;
}

.node-drawer__memory-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.node-drawer__memory-date {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}

.node-drawer__memory-event {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.node-drawer__memory-edit-btn {
  flex-shrink: 0;
}

.node-drawer__memory-delete {
  flex-shrink: 0;
}

.node-drawer__memory-content {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
}

.node-drawer__memory-detail {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-top: 4px;
}

.node-drawer__memory-reflection {
  font-size: 13px;
  font-style: italic;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-top: 4px;
}

.node-drawer__memory-involved {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;

  .node-drawer__field-label {
    font-size: 12px;
    margin-right: 2px;
  }
}

.node-drawer__memory-involved-tag {
  font-size: 11px;
}


</style>
