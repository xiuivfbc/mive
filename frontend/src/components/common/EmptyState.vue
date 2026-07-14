<template>
  <div class="empty-state">
    <div class="empty-state__icon">
      <slot name="icon">
        <svg width="140" height="140" viewBox="0 0 48 48" fill="none">
          <circle cx="21" cy="22" r="15" stroke="currentColor" stroke-width="1.5" opacity="0.6" />
          <path d="M21 7C17 11 15 16 15 22C15 28 17 33 21 37" stroke="currentColor" stroke-width="1.2" opacity="0.4" />
          <path d="M21 7C25 11 27 16 27 22C27 28 25 33 21 37" stroke="currentColor" stroke-width="1.2" opacity="0.4" />
          <path d="M6.5 22H35.5" stroke="currentColor" stroke-width="1.2" opacity="0.4" />
          <path d="M9 14C12.5 16.5 16.5 18 21 18C25.5 18 29.5 16.5 33 14" stroke="currentColor" stroke-width="1.2" opacity="0.3" />
          <path d="M9 30C12.5 27.5 16.5 26 21 26C25.5 26 29.5 27.5 33 30" stroke="currentColor" stroke-width="1.2" opacity="0.3" />
          <path d="M35 30.5V39.5M30.5 35H39.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity="0.7" />
        </svg>
      </slot>
    </div>
    <h3 class="empty-state__title">{{ title }}</h3>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div class="empty-state__action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: calc(var(--spacing-2xl) * 1.5) 0;
  text-align: center;
}

.empty-state__icon {
  color: var(--color-text-faint);
  margin-bottom: var(--spacing-lg);
  animation: pulse 3s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.6; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.05); }
}

.empty-state__title {
  margin: 0 0 var(--spacing-sm);
  font-family: var(--font-display);
  font-size: 34px;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.empty-state__desc {
  margin: 0 0 var(--spacing-lg);
  color: var(--color-text-muted);
  font-size: 22px;
}

.empty-state__action {
  margin-top: var(--spacing-md);
}
</style>
