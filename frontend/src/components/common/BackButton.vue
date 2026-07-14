<template>
  <button class="back-button" type="button" @click="handleClick" :aria-label="label">
    <svg class="back-button__icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M9.5 3.5L5 8l4.5 4.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span class="back-button__label">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  label?: string
  to?: string
}>()

const router = useRouter()
const { t } = useI18n()

const label = computed(() => props.label ?? t('common.back'))

function handleClick() {
  if (props.to) {
    router.push(props.to)
  } else if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}
</script>

<style scoped>
.back-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: var(--font-md);
  cursor: pointer;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}

.back-button:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-primary);
}

.back-button__icon {
  flex-shrink: 0;
}

.back-button__label {
  line-height: 1;
}

@media (max-width: 768px) {
  .back-button__label {
    display: none;
  }

  .back-button {
    padding: 6px 10px;
  }
}
</style>
