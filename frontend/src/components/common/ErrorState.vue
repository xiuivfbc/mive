<template>
  <div class="error-state">
    <div class="error-state__icon">
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="1.5" opacity="0.5" />
        <path d="M18 30l6-6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="24" cy="18" r="2" fill="currentColor" />
      </svg>
    </div>
    <p class="error-state__message">{{ message }}</p>
    <NButton type="primary" size="small" @click="$emit('retry')">{{ $t('error.retry') }}</NButton>
  </div>
</template>

<script setup lang="ts">
import { NButton } from 'naive-ui'

defineProps<{
  message: string
}>()

defineEmits<{
  retry: []
}>()
</script>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-2xl) 0;
}

.error-state__icon {
  color: var(--color-error);
  animation: shake 0.4s ease-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-4px); }
  40% { transform: translateX(4px); }
  60% { transform: translateX(-2px); }
  80% { transform: translateX(2px); }
}

.error-state__message {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-md);
  text-align: center;
  max-width: 400px;
}
</style>
