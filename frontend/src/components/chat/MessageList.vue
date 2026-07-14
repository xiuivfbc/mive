<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { Message } from '@/types/message'
import MessageBubble from './MessageBubble.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const props = defineProps<{
  messages: Message[]
  hasMore: boolean
  loading: boolean
  currentEventId?: string | null
  characterPortraitMap?: Record<string, string>
  /** Character name map: sender_id -> name, for resolving sender names */
  characterNameMap?: Record<string, string>
  /** Map of character_id -> {name, portrait_url} for per-message user role identity */
  userCharacterMap?: Record<string, { name: string; portrait_url: string | null }>
}>()

const emit = defineEmits<{
  'load-more': []
  'avatar-click': [payload: { characterId: string; characterName: string }]
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let prevScrollHeight = 0

function onScroll() {
  const el = containerRef.value
  if (!el) return
  if (el.scrollTop <= 10 && props.hasMore && !props.loading) {
    prevScrollHeight = el.scrollHeight
    emit('load-more')
  }
}

// loadMore 后恢复滚动位置
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    const el = containerRef.value
    if (el && prevScrollHeight > 0) {
      const newScrollHeight = el.scrollHeight
      el.scrollTop = newScrollHeight - prevScrollHeight
      prevScrollHeight = 0
    }
  }
)

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  const el = containerRef.value
  if (el) {
    el.scrollTo({ top: el.scrollHeight, behavior })
  }
}

defineExpose({ scrollToBottom })
</script>

<template>
  <div
    ref="containerRef"
    class="message-list"
    @scroll="onScroll"
  >
    <div v-if="loading && hasMore" class="message-list__loader">
      <LoadingState :rows="1" />
    </div>

    <div v-if="!hasMore && messages.length > 0" class="message-list__top">
      {{ $t('chat.atTop') }}
    </div>

    <EmptyState
      v-if="!loading && messages.length === 0"
      :title="$t('chat.emptyTitle')"
      :description="$t('chat.emptyDesc')"
    >
      <template #icon>
        <svg width="140" height="140" viewBox="0 0 48 48" fill="none">
          <path d="M10 15C10 12.8 11.8 11 14 11H34C36.2 11 38 12.8 38 15V29C38 31.2 36.2 33 34 33H27L19 40V33H14C11.8 33 10 31.2 10 29V15Z" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
          <path d="M17 20H31" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" opacity="0.4" />
          <path d="M17 24H27" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" opacity="0.4" />
        </svg>
      </template>
    </EmptyState>

    <MessageBubble
      v-for="msg in messages"
      :key="msg.id"
      :message="msg"
      :is-current="msg.type === 'event' && msg.id === currentEventId"
      :portrait-url="msg.sender_id ? characterPortraitMap?.[msg.sender_id] : undefined"
      :character-id="msg.sender_id"
      :character-name-map="characterNameMap"
      :user-character-map="userCharacterMap"
      @avatar-click="emit('avatar-click', $event)"
    />
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  scroll-behavior: smooth;
}

.message-list__loader,
.message-list__top {
  text-align: center;
  padding: 10px;
  color: var(--text-muted);
  font-size: 14px;
  opacity: 0.6;
}
</style>
