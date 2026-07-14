<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'
import { updateRelation, deleteRelation } from '@/api/relations'
import { parseApiError } from '@/utils/apiError'
import {
  NDrawer, NDrawerContent, NTag, NButton, NInput, NSelect, NSpace, NSpin, NPopconfirm, useMessage,
} from 'naive-ui'

const props = defineProps<{
  visible: boolean
  worldId: string
  relations: Relation[]
  characters: Character[]
}>()

const emit = defineEmits<{
  'update:visible': [v: boolean]
  'relation-updated': [r: Relation]
  'relation-deleted': [id: string]
}>()

const { t } = useI18n()
const messageApi = useMessage()

function nameOf(id: string): string {
  return props.characters.find(c => c.id === id)?.name ?? t('graph.unknownName')
}

// 两人之间共同的一对角色信息（用于抽屉头部展示），取列表首条即可——同一 pair 的记录角色对相同
const pairChars = computed(() => {
  const first = props.relations[0]
  if (!first) return { a: undefined as Character | undefined, b: undefined as Character | undefined }
  return {
    a: props.characters.find(c => c.id === first.character_a),
    b: props.characters.find(c => c.id === first.character_b),
  }
})

function directionArrow(item: Relation): string {
  if (item.direction === 'a_to_b') return '→'
  if (item.direction === 'b_to_a') return '←'
  return '↔'
}

function directionOptions(item: Relation) {
  const aName = nameOf(item.character_a)
  const bName = nameOf(item.character_b)
  return [
    { label: `${aName} ↔ ${bName}`, value: 'bidirectional' },
    { label: `${aName} → ${bName}`, value: 'a_to_b' },
    { label: `${bName} → ${aName}`, value: 'b_to_a' },
  ]
}

// 每条关系记录独立的编辑/保存/删除状态，互不影响
interface ItemState {
  editing: boolean
  saving: boolean
  deleting: boolean
  editType: string
  editDescription: string
  editDirection: string
}

const itemStates = reactive<Record<string, ItemState>>({})

function ensureState(id: string): ItemState {
  if (!itemStates[id]) {
    itemStates[id] = {
      editing: false,
      saving: false,
      deleting: false,
      editType: '',
      editDescription: '',
      editDirection: 'bidirectional',
    }
  }
  return itemStates[id]
}

watch(
  () => props.relations,
  (list) => {
    const ids = new Set(list.map(r => r.id))
    for (const id of Object.keys(itemStates)) {
      if (!ids.has(id)) delete itemStates[id]
    }
    list.forEach(r => ensureState(r.id))
  },
  { immediate: true },
)

function startEdit(item: Relation) {
  const s = itemStates[item.id]
  s.editType = item.type ?? ''
  s.editDescription = item.description ?? ''
  s.editDirection = item.direction ?? 'bidirectional'
  s.editing = true
}

function cancelEdit(item: Relation) {
  itemStates[item.id].editing = false
}

async function saveEdit(item: Relation) {
  const s = itemStates[item.id]
  s.saving = true
  try {
    const updated = await updateRelation(props.worldId, item.id, {
      type: s.editType || null,
      description: s.editDescription || null,
      direction: s.editDirection,
    })
    emit('relation-updated', updated)
    messageApi.success(t('graph.relationUpdated'))
    s.editing = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    s.saving = false
  }
}

async function onDelete(item: Relation) {
  const s = itemStates[item.id]
  if (s.deleting) return
  s.deleting = true
  try {
    await deleteRelation(props.worldId, item.id)
    messageApi.success(t('graph.relationDeleted'))
    emit('relation-deleted', item.id)
  } catch (e) {
    messageApi.error(parseApiError(e, t))
    s.deleting = false
  }
}
</script>

<template>
  <NDrawer
    :show="visible"
    :width="440"
    @update:show="(v: boolean) => emit('update:visible', v)"
  >
    <NDrawerContent
      v-if="relations.length"
      closable
    >
      <div class="edge-drawer__chars">
        <div class="edge-drawer__char">
          <div class="edge-drawer__avatar">{{ (pairChars.a?.name ?? '?').charAt(0) }}</div>
          <span>{{ pairChars.a?.name ?? $t('graph.unknownName') }}</span>
        </div>
        <span class="edge-drawer__arrow">↔</span>
        <div class="edge-drawer__char">
          <div class="edge-drawer__avatar">{{ (pairChars.b?.name ?? '?').charAt(0) }}</div>
          <span>{{ pairChars.b?.name ?? $t('graph.unknownName') }}</span>
        </div>
      </div>

      <div class="edge-drawer__list">
        <div v-for="item in relations" :key="item.id" class="edge-drawer__item">
          <NSpin :show="!!itemStates[item.id]?.saving || !!itemStates[item.id]?.deleting">
            <!-- 查看态 -->
            <template v-if="!itemStates[item.id]?.editing">
              <div class="edge-drawer__item-top">
                <div class="edge-drawer__item-meta">
                  <NTag v-if="item.type" round size="small">{{ item.type }}</NTag>
                  <span class="edge-drawer__item-direction">
                    {{ nameOf(item.character_a) }} {{ directionArrow(item) }} {{ nameOf(item.character_b) }}
                  </span>
                </div>
                <div class="edge-drawer__item-actions">
                  <NButton size="tiny" quaternary @click="startEdit(item)">{{ $t('common.edit') }}</NButton>
                  <NPopconfirm @positive-click="onDelete(item)">
                    <template #trigger>
                      <NButton size="tiny" quaternary type="error">{{ $t('common.delete') }}</NButton>
                    </template>
                    {{ $t('graph.deleteRelationConfirm') }}
                  </NPopconfirm>
                </div>
              </div>
              <p
                class="edge-drawer__item-desc"
                :class="{ 'edge-drawer__item-desc--empty': !item.description }"
              >
                {{ item.description || $t('graph.noDetail') }}
              </p>
            </template>

            <!-- 编辑态：在该条目内展开 -->
            <template v-else>
              <div class="edge-drawer__edit-form">
                <div class="edge-drawer__field">
                  <label class="edge-drawer__field-label">{{ $t('manualEdit.relationTypePlaceholder') }}</label>
                  <NInput
                    v-model:value="itemStates[item.id].editType"
                    :placeholder="$t('manualEdit.relationTypePlaceholder')"
                  />
                </div>
                <div class="edge-drawer__field">
                  <label class="edge-drawer__field-label">{{ $t('manualEdit.direction') }}</label>
                  <NSelect
                    v-model:value="itemStates[item.id].editDirection"
                    :options="directionOptions(item)"
                  />
                </div>
                <div class="edge-drawer__field">
                  <label class="edge-drawer__field-label">{{ $t('manualEdit.relationDescPlaceholder') }}</label>
                  <NInput
                    v-model:value="itemStates[item.id].editDescription"
                    type="textarea"
                    :placeholder="$t('manualEdit.relationDescPlaceholder')"
                    :autosize="{ minRows: 2, maxRows: 6 }"
                  />
                </div>
              </div>
              <NSpace class="edge-drawer__edit-actions">
                <NButton
                  type="primary"
                  size="small"
                  :loading="itemStates[item.id].saving"
                  @click="saveEdit(item)"
                >{{ $t('common.save') }}</NButton>
                <NButton
                  size="small"
                  :disabled="itemStates[item.id].saving"
                  @click="cancelEdit(item)"
                >{{ $t('common.cancel') }}</NButton>
              </NSpace>
            </template>
          </NSpin>
        </div>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.edge-drawer__chars {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: var(--spacing-md) 0;
}

.edge-drawer__char {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 600;
}

.edge-drawer__avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-deep);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  font-family: var(--font-display);
}

.edge-drawer__arrow {
  font-size: 20px;
  color: var(--text-muted);
}

.edge-drawer__list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  padding-top: var(--spacing-md);
}

.edge-drawer__item {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
}

.edge-drawer__item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.edge-drawer__item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.edge-drawer__item-direction {
  font-size: 12px;
  color: var(--text-secondary);
}

.edge-drawer__item-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.edge-drawer__item-desc {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
  margin: 8px 0 0;
}

.edge-drawer__item-desc--empty {
  color: var(--text-muted);
}

.edge-drawer__edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.edge-drawer__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edge-drawer__field-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}

.edge-drawer__edit-actions {
  margin-top: 12px;
}

</style>
