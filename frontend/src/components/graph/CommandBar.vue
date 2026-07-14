<template>
  <div class="command-bar">
    <div class="cb-header">
      <span class="cb-hint-key">{{ $t('commandBar.executeHint') }}</span>
    </div>

    <!-- 输入区 -->
    <div class="cb-input-section">
      <div class="cb-input-wrap" :class="{ focused: inputFocused }">
        <span class="cb-prompt">›</span>
        <input
          ref="inputRef"
          v-model="command"
          class="cb-input"
          :disabled="isBusy"
          :placeholder="isBusy ? $t('commandBar.busyPlaceholder') : $t('commandBar.placeholder')"
          autocomplete="off"
          spellcheck="false"
          @focus="onInputFocus"
          @blur="onInputBlur"
          @keydown.enter="onSubmit"
          @keydown.escape="onCancel"
          @input="resolveError = ''"
        />
      </div>
      <div class="cb-syntax-row">
        <button class="cb-bracket-chip" :disabled="isBusy" @click="insertBracket('[', ']')">[a]</button>
        <button class="cb-bracket-chip" :disabled="isBusy" @click="insertBracket('【', '】')">【a】</button>
        <span class="cb-syntax-label">{{ $t('commandBar.insertBracketHint') }}</span>
      </div>
      <div class="cb-example" :class="{ disabled: isBusy }" @click="!isBusy && fillExample('删除[a]的和其他非core角色的关系')">
        {{ $t('commandBar.exampleHint') }}
      </div>
    </div>

    <!-- 无效代号提示 -->
    <div v-if="resolveError" class="cb-resolve-error">{{ resolveError }}</div>

    <!-- 解析中 -->
    <div v-if="parsing" class="cb-parsing">
      <span class="cb-dot-anim" />
      <span>{{ $t('commandBar.parsing') }}</span>
      <span class="cb-busy-hint">{{ $t('commandBar.inputDisabled') }}</span>
    </div>

    <!-- 预览 -->
    <div v-if="preview && !parsing" class="cb-preview">
      <div class="cb-preview-title">{{ $t('commandBar.previewTitle') }}</div>
      <div v-if="preview.operations.length === 0" class="cb-empty">{{ $t('commandBar.noOperations') }}</div>
      <div v-else class="cb-preview-list">
        <div
          v-for="(op, i) in preview.operations"
          :key="i"
          class="diff-item"
          :class="opClass(op.op)"
        >
          <span class="diff-sign">{{ opSign(op.op) }}</span>
          <div class="diff-content">
            <span class="diff-label">{{ opLabel(op) }}</span>
            <span class="diff-meta">{{ opMeta(op) }}</span>
          </div>
        </div>
      </div>
      <div v-if="preview.operations.length > 0" class="cb-actions">
        <button class="btn-confirm" :disabled="applying" @click="onApply">
          {{ applying ? $t('commandBar.applyingButton') : $t('commandBar.applyButton') }}
        </button>
        <button class="btn-cancel" :disabled="applying" @click="onCancel">{{ $t('common.cancel') }}</button>
      </div>
    </div>

    <!-- 操作记录 -->
    <div class="cb-history">
      <div class="cb-section-title">{{ $t('commandBar.historyTitle') }}</div>
      <div v-if="history.length === 0" class="cb-empty">{{ $t('commandBar.noHistory') }}</div>
      <div v-for="(h, i) in history" :key="i" class="history-item">
        <span class="history-time">{{ h.time }}</span>
        <span class="history-cmd">{{ h.command }}</span>
        <span class="history-badge">✓</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { parseCommand, applyCommand } from '@/api/graphCommand'
import type { ParseResult, GraphOperation } from '@/api/graphCommand'
import type { Character } from '@/types/character'
import { useLocale } from '@/composables/useLocale'
import { genCode } from '@/utils/codeMap'

const props = defineProps<{ worldId: string; characters?: Character[] }>()
const emit = defineEmits<{
  (e: 'applied'): void
  (e: 'focus-change', v: boolean): void
}>()

const { t } = useI18n()
const { locale } = useLocale()

// code → character name（按传入顺序稳定）
const codeMap = computed(() => {
  const m = new Map<string, string>()
  ;(props.characters ?? []).forEach((c, i) => m.set(genCode(i), c.name))
  return m
})

const inputRef = ref<HTMLInputElement>()
const command = ref('')
const inputFocused = ref(false)
const parsing = ref(false)
const applying = ref(false)
const preview = ref<ParseResult | null>(null)
const history = ref<{ time: string; command: string }[]>([])

const isBusy = computed(() => parsing.value || applying.value)

function onInputFocus() {
  inputFocused.value = true
  emit('focus-change', true)
}
function onInputBlur() {
  inputFocused.value = false
  emit('focus-change', false)
}

function fillExample(ex: string) {
  command.value = ex
  inputRef.value?.focus()
}

function insertBracket(open: string, close: string) {
  const el = inputRef.value
  if (!el) { command.value += open + close; return }
  const start = el.selectionStart ?? command.value.length
  const end = el.selectionEnd ?? start
  command.value = command.value.slice(0, start) + open + close + command.value.slice(end)
  nextTick(() => { el.focus(); el.setSelectionRange(start + open.length, start + open.length) })
}

// 将命令里的 [x]/【x】 替换为 @真实角色名（方便后端精确识别角色边界）
function resolveCodes(cmd: string): { resolved: string; invalid: string[] } {
  // 第一步：提取所有括号内容，找出无效代号
  const invalid: string[] = []
  const pattern = /\[([^\]]*)\]|【([^】]*)】/g
  let m: RegExpExecArray | null
  while ((m = pattern.exec(cmd)) !== null) {
    const code = m[1] ?? m[2]
    const isEn = m[1] !== undefined
    if (!codeMap.value.has(code)) {
      invalid.push(isEn ? `[${code}]` : `【${code}】`)
    }
  }
  if (invalid.length) return { resolved: '', invalid }

  // 第二步：全部合法，统一替换为 @name
  const resolved = cmd
    .replace(/\[([^\]]*)\]/g, (_, code) => `@${codeMap.value.get(code)}`)
    .replace(/【([^】]*)】/g, (_, code) => `@${codeMap.value.get(code)}`)
  return { resolved, invalid: [] }
}

const resolveError = ref('')

async function onSubmit() {
  const raw = command.value.trim()
  if (!raw || isBusy.value) return
  const { resolved, invalid } = resolveCodes(raw)
  if (invalid.length) {
    resolveError.value = `无效代号：${invalid.join('、')}`
    return
  }
  resolveError.value = ''
  preview.value = null
  parsing.value = true
  try {
    preview.value = await parseCommand(props.worldId, resolved)
  } catch (e) {
    console.error('[CommandBar] parse error', e)
  } finally {
    parsing.value = false
  }
}

async function onApply() {
  if (!preview.value || applying.value) return
  applying.value = true
  try {
    await applyCommand(props.worldId, preview.value.operations)
    history.value.unshift({
      time: new Date().toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }),
      command: command.value.trim(),
    })
    command.value = ''
    preview.value = null
    emit('applied')
  } catch (e) {
    console.error('[CommandBar] apply error', e)
  } finally {
    applying.value = false
  }
}

function onCancel() {
  preview.value = null
  command.value = ''
  inputRef.value?.blur()
}

// ── 显示辅助 ─────────────────────────────────────────────────────────────

function opClass(op: string) {
  if (op.startsWith('add')) return 'add'
  if (op.startsWith('delete')) return 'del'
  return 'mod'
}

function opSign(op: string) {
  if (op.startsWith('add')) return '+'
  if (op.startsWith('delete')) return '−'
  return '~'
}

function opLabel(op: GraphOperation): string {
  switch (op.op) {
    case 'add_character':    return t('commandBar.addCharacter', { name: op.name })
    case 'delete_character': return t('commandBar.deleteCharacter', { name: op.name })
    case 'update_character': return t('commandBar.updateCharacter', { name: op.name })
    case 'add_relation':     return t('commandBar.addRelation', { a: op.character_a, b: op.character_b })
    case 'delete_relation':  return t('commandBar.deleteRelation', { a: op.character_a, b: op.character_b })
    case 'update_relation':  return t('commandBar.updateRelation', { a: op.character_a, b: op.character_b })
    default:                 return op.op
  }
}

function opMeta(op: GraphOperation): string {
  switch (op.op) {
    case 'add_character':
      return [op.tier, op.occupation, op.brief].filter(Boolean).join(' · ')
    case 'add_relation':
      return [op.type, op.direction].filter(Boolean).join(' · ')
    case 'update_character':
    case 'update_relation':
      return Object.entries(op.changes || {}).map(([k, v]) => `${k}: ${v}`).join('，')
    default:
      return ''
  }
}
</script>

<style scoped>
.command-bar {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  font-size: 13px;
  overflow-y: auto;
}

.cb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}
.cb-hint-key {
  font-family: monospace;
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-elevated);
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(0,0,0,0.08);
}

/* 输入区 */
.cb-input-section {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}
.cb-input-wrap {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 5px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.cb-input-wrap.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-dim);
}
.cb-prompt {
  font-family: monospace;
  font-size: 14px;
  color: var(--accent);
  padding: 0 6px 0 10px;
  opacity: 0.7;
  flex-shrink: 0;
}
.cb-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 12px;
  color: var(--text-primary);
  padding: 8px 8px 8px 0;
  font-family: inherit;
  caret-color: var(--accent);
}
.cb-input::placeholder { color: var(--text-faint); font-size: 11px; }
.cb-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cb-syntax-row {
  margin-top: 7px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.cb-bracket-chip {
  font-family: "Courier New", monospace;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 3px;
  background: var(--bg-elevated);
  color: var(--accent);
  cursor: pointer;
  transition: all 0.15s;
}
.cb-bracket-chip:hover:not(:disabled) { border-color: var(--accent); }
.cb-bracket-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.cb-syntax-label {
  font-size: 10px;
  color: var(--text-faint);
}
.cb-example {
  margin-top: 6px;
  font-size: 10px;
  color: var(--text-faint);
  cursor: pointer;
  line-height: 1.5;
  transition: color 0.15s;
}
.cb-example:hover:not(.disabled) { color: var(--text-muted); }
.cb-example.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.cb-chip {
  font-size: 10px;
  padding: 2px 7px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 3px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.cb-chip:hover { color: var(--text-primary); border-color: var(--border); }

.cb-resolve-error {
  padding: 6px 14px;
  font-size: 11px;
  color: var(--color-error);
  border-bottom: 1px solid rgba(0,0,0,0.06);
}

/* 解析中 */
.cb-parsing {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--accent);
  border-bottom: 1px solid rgba(0,0,0,0.06);
}
.cb-dot-anim {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: blink 0.9s ease infinite;
  flex-shrink: 0;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
.cb-busy-hint {
  font-size: 10px;
  color: var(--text-faint);
  margin-left: auto;
}

/* 预览 */
.cb-preview {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.cb-preview-list {
  max-height: 240px;
  overflow-y: auto;
  min-height: 0;
}
.cb-preview-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.diff-item {
  display: flex;
  gap: 7px;
  padding: 6px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
  animation: slide-in 0.2s ease;
}
@keyframes slide-in { from{opacity:0;transform:translateX(-5px)} to{opacity:1;transform:none} }
.diff-item.add { background: rgba(61,232,160,0.08); }
.diff-item.del { background: rgba(240,80,96,0.08); }
.diff-item.mod { background: rgba(240,192,64,0.08); }
.diff-sign {
  font-weight: 700;
  font-family: monospace;
  font-size: 13px;
  flex-shrink: 0;
  line-height: 1.4;
}
.add .diff-sign { color: var(--color-success); }
.del .diff-sign { color: var(--color-error); }
.mod .diff-sign { color: var(--accent); }
.diff-content { display: flex; flex-direction: column; gap: 2px; }
.diff-label { font-size: 12px; color: var(--text-primary); }
.diff-meta { font-size: 10px; color: var(--text-muted); font-family: monospace; }

.cb-actions {
  display: flex;
  gap: 7px;
  margin-top: 10px;
}
.btn-confirm {
  flex: 1;
  padding: 7px;
  background: var(--accent);
  color: var(--bg-deep);
  border: none;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-confirm:hover:not(:disabled) { opacity: 0.85; }
.btn-confirm:disabled { opacity: 0.5; cursor: default; }
.btn-cancel {
  padding: 7px 14px;
  background: transparent;
  color: var(--text-muted);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-cancel:hover:not(:disabled) { color: var(--text-primary); border-color: var(--border); }
.btn-cancel:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 历史 */
.cb-history {
  flex: 1;
  padding: 10px 12px;
  overflow-y: auto;
  min-height: 0;
}
.cb-section-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-faint);
  margin-bottom: 8px;
}
.cb-empty {
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
.history-time {
  font-family: monospace;
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.history-cmd {
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

@media (max-width: 768px) {
  /* 移动端隐藏操作记录，节省空间 */
  .cb-history {
    display: none;
  }

  /* 移动端缩小控件 */
  .command-bar {
    font-size: 11px;
  }

  .cb-header {
    padding: 5px 8px 4px;
  }

  .cb-hint-key {
    font-size: 8px;
    padding: 0 4px;
  }

  .cb-input-section {
    padding: 5px 8px;
  }

  .cb-input-wrap {
    border-radius: 4px;
  }

  .cb-prompt {
    font-size: 10px;
    padding: 0 3px 0 6px;
  }

  .cb-input {
    font-size: 10px;
    padding: 4px 5px 4px 0;
  }

  .cb-input::placeholder {
    font-size: 9px;
  }

  .cb-syntax-row {
    margin-top: 4px;
    gap: 3px;
  }

  .cb-bracket-chip {
    font-size: 9px;
    padding: 1px 4px;
  }

  .cb-syntax-label {
    font-size: 8px;
  }

  .cb-example {
    margin-top: 3px;
    font-size: 8px;
  }

  .cb-resolve-error {
    padding: 4px 8px;
    font-size: 10px;
  }

  .cb-parsing {
    padding: 6px 8px;
    font-size: 10px;
    gap: 5px;
  }

  .cb-dot-anim {
    width: 4px;
    height: 4px;
  }

  .cb-busy-hint {
    font-size: 8px;
  }

  .cb-preview {
    padding: 6px 8px;
  }

  .cb-preview-title {
    font-size: 8px;
    margin-bottom: 4px;
  }

  .cb-preview-list {
    max-height: 160px;
  }

  .diff-item {
    padding: 3px 5px;
    gap: 4px;
    margin-bottom: 2px;
  }

  .diff-sign {
    font-size: 10px;
  }

  .diff-label {
    font-size: 10px;
  }

  .diff-meta {
    font-size: 8px;
  }

  .cb-actions {
    gap: 5px;
    margin-top: 6px;
  }

  .btn-confirm {
    padding: 4px;
    font-size: 10px;
  }

  .btn-cancel {
    padding: 4px 8px;
    font-size: 10px;
  }
}
</style>
