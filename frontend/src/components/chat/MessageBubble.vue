<script setup lang="ts">
import type { Message, EventCard } from '@/types/message'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCharacterColors } from '@/composables/useCharacterColors'

interface UserCharacterInfo {
  name: string
  portrait_url: string | null
}

const props = defineProps<{
  message: Message
  isCurrent?: boolean
  portraitUrl?: string | null
  characterId?: string | null
  /** Character name map: sender_id -> name, for resolving names when sender_name is null */
  characterNameMap?: Record<string, string>
  /** Map of character_id -> {name, portrait_url} for resolving per-message user role identity */
  userCharacterMap?: Record<string, UserCharacterInfo>
}>()

const emit = defineEmits<{ 'avatar-click': [payload: { characterId: string; characterName: string }] }>()

const { t } = useI18n()
const { getColor } = useCharacterColors()

/** Resolve display name: sender_name (legacy) -> characterNameMap lookup -> sender_type fallback */
const resolvedName = computed(() => {
  if (props.message.sender_name) return props.message.sender_name
  if (props.message.sender_id && props.characterNameMap?.[props.message.sender_id]) {
    return props.characterNameMap[props.message.sender_id]
  }
  const typeNames: Record<string, string> = { system: '系统', narrator: '旁白', user: '用户' }
  return typeNames[props.message.sender_type] ?? '?'
})

/** Per-message user role display name (resolves from message.sender_id; does not fall back to the
 * "currently" role-played identity, so switching roles doesn't repaint older messages) */
const perMessageUserDisplayName = computed(() => {
  if (props.message.sender_id && props.userCharacterMap?.[props.message.sender_id]) {
    return props.userCharacterMap[props.message.sender_id].name
  }
  return undefined
})

/** Per-message user role avatar URL (resolves from message.sender_id; see perMessageUserDisplayName) */
const perMessageUserAvatarUrl = computed(() => {
  if (props.message.sender_id && props.userCharacterMap?.[props.message.sender_id]) {
    return props.userCharacterMap[props.message.sender_id].portrait_url
  }
  return null
})

/** Resolved display name for the user bubble, including the "explorer" default fallback */
const resolvedUserDisplayName = computed(() => perMessageUserDisplayName.value ?? t('chat.defaultRole'))

const isNarration = computed(() => props.message.sender_type === 'narrator')
const isUser = computed(() => props.message.sender_type === 'user')
const isSystem = computed(() => props.message.sender_type === 'system')
const isCharacter = computed(() => props.message.sender_type === 'character')
const isFailed = computed(() => props.message.status === 'failed' && props.message.sender_type === 'user')

const characterColor = computed(() =>
  isCharacter.value ? getColor(resolvedName.value) : ''
)

type Segment = { type: 'action' | 'dialogue'; text: string }

function parseContent(content: string): Segment[] {
  const segments: Segment[] = []
  const regex = /\*([^*]+)\*/g
  let lastIndex = 0
  let match
  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      const text = content.slice(lastIndex, match.index).trim()
      if (text) segments.push({ type: 'dialogue', text })
    }
    segments.push({ type: 'action', text: match[1].trim() })
    lastIndex = regex.lastIndex
  }
  if (lastIndex < content.length) {
    const text = content.slice(lastIndex).trim()
    if (text) segments.push({ type: 'dialogue', text })
  }
  return segments.length ? segments : [{ type: 'dialogue', text: content }]
}

const parsedContent = computed(() =>
  isCharacter.value ? parseContent(props.message.content) : []
)

function onAvatarClick() {
  if (props.characterId && isCharacter.value) {
    emit('avatar-click', { characterId: props.characterId, characterName: resolvedName.value })
  }
}

const eventCard = computed<EventCard>(() => {
  if (props.message.type !== 'event') return { title: '', description: '', participants: [] }
  try {
    return JSON.parse(props.message.content) as EventCard
  } catch {
    return { title: props.message.content, description: '', participants: [] }
  }
})
</script>

<template>
  <!-- 事件卡片（优先判断） -->
  <div v-if="message.type === 'event'" class="event-card" :class="{ 'event-card--current': isCurrent }">
    <div class="event-card__header">
      <span class="event-card__icon">⚡</span>
      <span class="event-card__title">{{ eventCard.title }}</span>
      <span v-if="isCurrent" class="event-card__current-badge">{{ $t('chat.currentBadge') }}</span>
    </div>
    <p class="event-card__desc">{{ eventCard.description }}</p>
    <div class="event-card__participants">
      <span
        v-for="name in eventCard.participants"
        :key="name"
        class="event-card__tag"
      >{{ name }}</span>
    </div>
  </div>

  <div
    v-else
    class="message-bubble"
    :class="{
      'message-bubble--narration': isNarration,
      'message-bubble--user': isUser,
      'message-bubble--system': isSystem,
      'message-bubble--character': isCharacter,
      'message-bubble--failed': isFailed,
    }"
  >
    <!-- 旁白 / 系统消息：居中 -->
    <template v-if="isNarration || isSystem">
      <div class="message-bubble__center">
        <span
          class="message-bubble__content"
          :class="{ 'message-bubble__content--italic': isNarration }"
        >{{ message.content }}</span>
      </div>
    </template>

    <!-- 角色对话：左侧 -->
    <template v-else-if="isCharacter">
      <div class="message-bubble__left">
        <div class="message-bubble__char-row">
          <div
            class="message-bubble__avatar message-bubble__avatar--clickable"
            :style="{ background: characterColor, '--char-color': characterColor }"
            :title="$t('character.setAvatar')"
            @click="onAvatarClick"
          >
            <img v-if="portraitUrl" :src="portraitUrl" class="message-bubble__avatar-img" />
            <span v-else>{{ resolvedName.charAt(0) }}</span>
          </div>
          <div>
            <div class="message-bubble__sender">
              {{ resolvedName }}
            </div>
            <div class="message-bubble__body">
              <template v-for="(seg, i) in parsedContent" :key="i">
                <span v-if="seg.type === 'action'" class="message-bubble__action">{{ seg.text }}</span>
                <span v-else class="message-bubble__dialogue">{{ seg.text }}</span>
              </template>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 用户发言：右侧（与角色气泡对称布局） -->
    <template v-else-if="isUser">
      <div class="message-bubble__right">
        <div v-if="isFailed" class="message-bubble__failed-hint">
          <span class="message-bubble__failed-icon">⚠</span>
          <span class="message-bubble__failed-text">{{ $t('chat.failedHint') }}</span>
        </div>
        <div class="message-bubble__char-row message-bubble__char-row--right">
          <div>
            <div class="message-bubble__sender message-bubble__sender--user">
              {{ resolvedUserDisplayName }}
            </div>
            <div class="message-bubble__body message-bubble__body--user">
              {{ message.content }}
            </div>
          </div>
          <div class="message-bubble__avatar message-bubble__avatar--user" style="--char-color: var(--accent)">
            <img v-if="perMessageUserAvatarUrl && (perMessageUserAvatarUrl.startsWith('http') || perMessageUserAvatarUrl.startsWith('data:') || perMessageUserAvatarUrl.startsWith('/'))" :src="perMessageUserAvatarUrl" class="message-bubble__avatar-img" />
            <span v-else>{{ resolvedUserDisplayName.charAt(0) }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-bubble {
  margin-bottom: 20px;
  animation: fadeIn 0.3s cubic-bezier(0.23, 1, 0.32, 1);
}

/* 居中样式 (narrator / system) */
.message-bubble__center {
  text-align: center;
  color: var(--text-muted);
  font-size: 15px;
  padding: 12px 0;
}

.message-bubble__content {
  display: inline-block;
  padding: 0;
  background: none;
  position: relative;
}

.message-bubble__content::before,
.message-bubble__content::after {
  content: '';
  display: inline-block;
  width: 28px;
  height: 1px;
  background: var(--border-subtle);
  vertical-align: middle;
  margin: 0 10px;
}

.message-bubble__content--italic {
  font-style: italic;
}

/* 角色气泡 (左侧) */
.message-bubble__left {
  max-width: 80%;
}

.message-bubble__char-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.message-bubble__avatar {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  overflow: hidden;
  margin-top: 2px;
  box-shadow: 0 0 0 2px var(--bg-deep), 0 0 0 4px var(--char-color, transparent);
  transition: opacity 0.15s, transform 0.15s;
}

.message-bubble__avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.message-bubble__avatar--clickable {
  cursor: pointer;
  transition: opacity 0.15s, transform 0.15s;
}
.message-bubble__avatar--clickable:hover {
  opacity: 0.8;
  transform: scale(1.08);
}

.message-bubble__sender {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 6px;
  padding-left: 4px;
  color: var(--text-secondary);
}

.message-bubble__body {
  display: inline-block;
  padding: 14px 22px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.6);
  line-height: 1.7;
  word-break: break-word;
  color: var(--text-primary);
  font-size: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 0 0 1px rgba(0, 0, 0, 0.04);
}

/* 用户气泡 (右侧) */
.message-bubble__right {
  max-width: 80%;
  margin-left: auto;
  text-align: right;
}

.message-bubble__char-row--right {
  justify-content: flex-end;
}

.message-bubble__char-row--right > div:first-child {
  text-align: right;
}

.message-bubble__sender--user {
  color: var(--text-secondary);
  text-align: right;
  padding-right: 4px;
  padding-left: 0;
}

.message-bubble__avatar--user {
  background: var(--accent-dim);
  color: var(--accent);
}


.message-bubble__body--user {
  background: rgba(255, 255, 255, 0.6);
  border-radius: 18px;
  text-align: left;
  color: var(--text-primary);
}

/* 失败消息 */
.message-bubble--failed .message-bubble__body--user {
  background: color-mix(in srgb, var(--color-error) 12%, rgba(255, 255, 255, 0.6));
  border-right-color: var(--color-error);
}

.message-bubble__failed-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
  margin-bottom: 4px;
  padding-right: 4px;
}

.message-bubble__failed-icon {
  color: var(--color-error);
  font-size: 13px;
}

.message-bubble__failed-text {
  color: var(--color-error);
  font-size: 13px;
  opacity: 0.85;
}

.message-bubble__action {
  color: var(--text-muted);
  font-style: italic;
}

.message-bubble__dialogue {
  font-weight: 400;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* === Event Card === */
.event-card {
  width: 100%;
  padding: 18px 22px;
  margin: 12px 0;
  border-radius: 8px;
  box-sizing: border-box;
  animation: fadeIn 0.3s cubic-bezier(0.23, 1, 0.32, 1);
}

.event-card__header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.event-card__icon {
  font-size: 16px;
  flex-shrink: 0;
}

.event-card__title {
  font-weight: 700;
  font-size: 17px;
  letter-spacing: 0.02em;
  flex: 1;
}

.event-card__current-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 9px;
  border-radius: 8px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.event-card__desc {
  font-size: 15px;
  margin: 0 0 12px 0;
  line-height: 1.6;
  opacity: 0.8;
}

.event-card__participants {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.event-card__tag {
  font-size: 13px;
  padding: 4px 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}

.event-card { background: color-mix(in srgb, var(--accent) 6%, transparent); border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent); }
.event-card--current { border-color: color-mix(in srgb, var(--accent) 55%, transparent); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 12%, transparent); }
.event-card__title { color: var(--accent); }
.event-card__desc { color: var(--text-secondary); }
.event-card__current-badge { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }

[data-mode="dark"] .message-bubble__body {
  background: rgba(255, 255, 255, 0.12);
}

[data-mode="dark"] .message-bubble__body--user {
  background: rgba(255, 255, 255, 0.12);
}

</style>
