<template>
  <button
    class="guide-fab"
    :aria-label="t('guide.button.label', '使用指南')"
    @click="$emit('click')"
  >
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  </button>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineEmits<{
  click: []
}>()

const { t } = useI18n()
</script>

<style scoped>
.guide-fab {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, transform 0.2s ease;
  flex-shrink: 0;
}

.guide-fab:hover {
  background: var(--accent-hover);
  transform: scale(1.1);
}

</style>
