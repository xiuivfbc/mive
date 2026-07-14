<template>
  <div class="loading-state">
    <div v-for="i in rows" :key="i" class="loading-state__row">
      <n-skeleton height="140px" width="100%" :sharp="false" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ rows?: number }>(), {
  rows: 3,
})
</script>

<style scoped>
.loading-state {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.loading-state__row {
  min-width: 280px;
  flex: 1;
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.loading-state__row :deep(.n-skeleton) {
  --n-color-start: var(--color-bg-secondary) !important;
  --n-color-end: var(--color-bg-elevated) !important;
}
</style>
