<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { NInput, NSelect, NButton, useMessage } from 'naive-ui'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'
import { createCharacter, updateCharacter, deleteCharacter } from '@/api/characters'
import { createRelation } from '@/api/relations'
import { parseApiError } from '@/utils/apiError'
import { useLocale } from '@/composables/useLocale'
import { genCode } from '@/utils/codeMap'

const props = defineProps<{
  worldId: string
  characters: Character[]
}>()

const emit = defineEmits<{
  'character-added': [c: Character]
  'relation-added': [r: Relation]
  'focus-change': [v: boolean]
}>()

const { t } = useI18n()
const messageApi = useMessage()
const { locale } = useLocale()

const activeSubTab = ref<'character' | 'relation'>('character')
const isMobile = ref(false)
let mql: MediaQueryList | null = null
function onMqlChange(e: MediaQueryListEvent) { isMobile.value = e.matches }
onMounted(() => {
  mql = window.matchMedia('(max-width: 768px)')
  isMobile.value = mql.matches
  mql.addEventListener('change', onMqlChange)
})
onBeforeUnmount(() => { mql?.removeEventListener('change', onMqlChange) })

const history = ref<{ time: string; text: string }[]>([])

function pushHistory(text: string) {
  history.value.unshift({
    time: new Date().toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }),
    text,
  })
}

// ── 添加角色 ──────────────────────────────────────────────────────────────
const newCharName = ref('')
const newCharTier = ref('supporting')
const newCharBrief = ref('')
const addingChar = ref(false)

const tierOptions = computed(() => [
  { label: t('graph.tierCore'), value: 'core' },
  { label: t('graph.tierSupporting'), value: 'supporting' },
  { label: t('graph.tierExtra'), value: 'extra' },
])

async function onAddCharacter() {
  const name = newCharName.value.trim()
  if (!name || addingChar.value) return
  addingChar.value = true
  try {
    const created = await createCharacter(props.worldId, {
      name,
      profile: { brief: newCharBrief.value.trim() || undefined },
    })
    try {
      const updated = await updateCharacter(props.worldId, created.id, { tier: newCharTier.value })
      emit('character-added', updated)
      pushHistory(t('manualEdit.historyCharacterAdded', { name: updated.name }))
      messageApi.success(t('manualEdit.characterAdded'))
    } catch (updateError) {
      // Rollback: delete the character if tier update fails
      await deleteCharacter(props.worldId, created.id)
      throw updateError
    }
    newCharName.value = ''
    newCharBrief.value = ''
    newCharTier.value = 'supporting'
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    addingChar.value = false
  }
}

// ── 添加关系 ──────────────────────────────────────────────────────────────
// 代号 → 角色（与画布上显示的代号顺序一致）
const codeMap = computed(() => {
  const m = new Map<string, Character>()
  props.characters.forEach((c, i) => m.set(genCode(i), c))
  return m
})

const relCodeA = ref('')
const relCodeB = ref('')
const relType = ref('')
const relDesc = ref('')
const relDirection = ref('bidirectional')
const addingRel = ref(false)

// 输入既可以是代号（a/b/...），也可以是角色名（不区分大小写）
function resolveCharacter(input: string): Character | null {
  const v = input.trim()
  if (!v) return null
  const byCode = codeMap.value.get(v.toLowerCase())
  if (byCode) return byCode
  return props.characters.find(c => c.name.toLowerCase() === v.toLowerCase()) ?? null
}

const charA = computed(() => resolveCharacter(relCodeA.value))
const charB = computed(() => resolveCharacter(relCodeB.value))

const codeError = computed(() => {
  const a = relCodeA.value.trim()
  const b = relCodeB.value.trim()
  if (a && !charA.value) return t('manualEdit.invalidCode', { code: a })
  if (b && !charB.value) return t('manualEdit.invalidCode', { code: b })
  if (charA.value && charB.value && charA.value.id === charB.value.id) {
    return t('manualEdit.sameCharacter')
  }
  return ''
})

const directionOptions = computed(() => {
  const nameA = charA.value?.name ?? 'A'
  const nameB = charB.value?.name ?? 'B'
  return [
    { label: `${nameA} ↔ ${nameB}`, value: 'bidirectional' },
    { label: `${nameA} → ${nameB}`, value: 'a_to_b' },
    { label: `${nameB} → ${nameA}`, value: 'b_to_a' },
  ]
})

const canAddRelation = computed(() =>
  !!charA.value && !!charB.value && charA.value.id !== charB.value.id && !codeError.value
)

function onCodeFocus() {
  emit('focus-change', true)
}
function onCodeBlur() {
  emit('focus-change', false)
}

async function onAddRelation() {
  if (!canAddRelation.value || addingRel.value) return
  addingRel.value = true
  try {
    const a = charA.value!
    const b = charB.value!
    const created = await createRelation(props.worldId, {
      character_a: a.id,
      character_b: b.id,
      type: relType.value.trim() || undefined,
      description: relDesc.value.trim() || undefined,
      direction: relDirection.value,
    })
    emit('relation-added', created)
    pushHistory(t('manualEdit.historyRelationAdded', { a: a.name, b: b.name }))
    messageApi.success(t('manualEdit.relationAdded'))
    relCodeA.value = ''
    relCodeB.value = ''
    relType.value = ''
    relDesc.value = ''
    relDirection.value = 'bidirectional'
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    addingRel.value = false
  }
}
</script>

<template>
  <div class="manual-edit">
    <div class="me-forms">
      <!-- 子 Tab 切换（移动端可见） -->
      <div class="me-sub-tabs">
        <button
          class="me-sub-tab"
          :class="{ active: activeSubTab === 'character' }"
          @click="activeSubTab = 'character'"
        >{{ $t('manualEdit.addCharacterButton') }}</button>
        <button
          class="me-sub-tab"
          :class="{ active: activeSubTab === 'relation' }"
          @click="activeSubTab = 'relation'"
        >{{ $t('manualEdit.addRelationButton') }}</button>
      </div>

      <!-- 添加角色 -->
      <div v-show="!isMobile || activeSubTab === 'character'" class="me-section">
        <div class="me-section-title">{{ $t('manualEdit.addCharacterTitle') }}</div>
        <NInput v-model:value="newCharName" size="small" :placeholder="$t('character.namePlaceholder')" @focus="onCodeFocus" @blur="onCodeBlur" />
        <NSelect v-model:value="newCharTier" size="small" :options="tierOptions" />
        <NInput
          v-model:value="newCharBrief"
          type="textarea"
          size="small"
          :placeholder="$t('character.briefPlaceholder')"
          :autosize="{ minRows: 2, maxRows: 3 }"
          @focus="onCodeFocus"
          @blur="onCodeBlur"
        />
        <NButton
          size="small"
          type="primary"
          block
          :loading="addingChar"
          :disabled="!newCharName.trim()"
          @click="onAddCharacter"
        >
          {{ $t('manualEdit.addCharacterButton') }}
        </NButton>
      </div>

      <!-- 添加关系 -->
      <div v-show="!isMobile || activeSubTab === 'relation'" class="me-section">
        <div class="me-section-title">{{ $t('manualEdit.addRelationTitle') }}</div>
        <div class="me-code-row">
          <input
            v-model="relCodeA"
            class="me-code-input"
            :placeholder="$t('manualEdit.codeAPlaceholder')"
            @focus="onCodeFocus"
            @blur="onCodeBlur"
          />
          <span class="me-code-sep">↔</span>
          <input
            v-model="relCodeB"
            class="me-code-input"
            :placeholder="$t('manualEdit.codeBPlaceholder')"
            @focus="onCodeFocus"
            @blur="onCodeBlur"
          />
        </div>
        <div v-if="codeError" class="me-code-error">{{ codeError }}</div>
        <div v-else-if="charA && charB" class="me-code-resolved">{{ charA.name }} ↔ {{ charB.name }}</div>
        <NInput v-model:value="relType" size="small" :placeholder="$t('manualEdit.relationTypePlaceholder')" @focus="onCodeFocus" @blur="onCodeBlur" />
        <NInput
          v-model:value="relDesc"
          type="textarea"
          size="small"
          :placeholder="$t('manualEdit.relationDescPlaceholder')"
          :autosize="{ minRows: 2, maxRows: 3 }"
          @focus="onCodeFocus"
          @blur="onCodeBlur"
        />
        <NSelect v-model:value="relDirection" size="small" :options="directionOptions" />
        <NButton
          size="small"
          type="primary"
          block
          :loading="addingRel"
          :disabled="!canAddRelation"
          @click="onAddRelation"
        >
          {{ $t('manualEdit.addRelationButton') }}
        </NButton>
      </div>
    </div>

    <!-- 操作记录 -->
    <div class="me-history">
      <div class="me-section-title">{{ $t('commandBar.historyTitle') }}</div>
      <div v-if="history.length === 0" class="me-empty">{{ $t('commandBar.noHistory') }}</div>
      <div v-for="(h, i) in history" :key="i" class="history-item">
        <span class="history-time">{{ h.time }}</span>
        <span class="history-text">{{ h.text }}</span>
        <span class="history-badge">✓</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.manual-edit {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  font-size: 13px;
  overflow: hidden;
}

.me-forms {
  flex-shrink: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.me-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.me-section-title {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}

/* 子 Tab 切换按钮 — 桌面端隐藏（两个表单同时显示） */
.me-sub-tabs {
  display: none;
}

.me-divider {
  height: 1px;
  background: var(--border-subtle);
  flex-shrink: 0;
}

/* 移动端：子 Tab 显示，切换表单 */
@media (max-width: 768px) {
  .me-sub-tabs {
    display: flex;
    border-bottom: 1px solid rgba(0,0,0,0.06);
    margin-bottom: 8px;
  }

  .me-sub-tab {
    flex: 1;
    padding: 8px 0;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }

  .me-sub-tab:hover {
    color: var(--text-primary);
  }

  .me-sub-tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }

  /* 隐藏分隔线（tab 切换替代） */
  .me-divider {
    display: none;
  }

  /* 移动端隐藏操作记录，节省空间 */
  .me-history {
    display: none;
  }

  /* 移动端缩小控件，与动口区保持一致 */
  .me-forms {
    padding: 5px 8px;
    gap: 4px;
  }

  .me-section {
    gap: 4px;
  }

  .me-section-title {
    font-size: 8px;
    margin-bottom: 0;
  }

  .me-forms :deep(.n-input) {
    --n-font-size: 10px;
    --n-height: 22px;
  }

  .me-forms :deep(.n-input--textarea) {
    --n-font-size: 10px;
  }

  .me-forms :deep(.n-select) {
    --n-height: 22px;
    --n-font-size: 10px;
  }

  .me-forms :deep(.n-button) {
    --n-height: 22px;
    --n-font-size: 10px;
  }

  .me-code-input {
    font-size: 10px;
    padding: 2px 4px;
  }

  .me-code-row {
    gap: 4px;
  }

  .me-code-sep {
    font-size: 9px;
  }

  .me-code-error,
  .me-code-resolved {
    font-size: 9px;
  }

  .me-sub-tabs {
    margin-bottom: 4px;
  }

  .me-sub-tab {
    padding: 4px 0;
    font-size: 10px;
  }
}

.me-code-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.me-code-input {
  flex: 1;
  min-width: 0;
  font-family: "Courier New", monospace;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  padding: 5px 8px;
  background: var(--bg-input);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
}

.me-code-input:focus {
  border-color: var(--accent);
}

.me-code-sep {
  flex-shrink: 0;
  color: var(--text-faint);
  font-size: 12px;
}

.me-code-error {
  font-size: 11px;
  color: var(--color-error);
}

.me-code-resolved {
  font-size: 11px;
  color: var(--text-secondary);
}

.me-history {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  border-top: 1px solid rgba(0,0,0,0.06);
}

.me-empty {
  font-size: 11px;
  color: var(--text-faint);
  padding: 4px 0;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  animation: slide-in 0.15s ease;
}

.history-item:last-child {
  border-bottom: none;
}

.history-time {
  font-family: monospace;
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.history-text {
  flex: 1;
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-badge {
  font-size: 10px;
  color: var(--color-success);
  flex-shrink: 0;
}

@keyframes slide-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
