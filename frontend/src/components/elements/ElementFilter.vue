<script setup lang="ts">
import { NTag } from 'naive-ui'

defineProps<{ categories: string[]; selected: string | null }>()
const emit = defineEmits<{ change: [value: string | null] }>()
</script>

<template>
  <div class="element-filter">
    <NTag
      :type="selected === null ? 'primary' : 'default'"
      checkable
      :checked="selected === null"
      round
      @update:checked="() => emit('change', null)"
      class="element-filter__tag"
    >
      {{ $t('element.filterAll') }}
    </NTag>
    <NTag
      v-for="cat in categories"
      :key="cat"
      :type="selected === cat ? 'primary' : 'default'"
      checkable
      :checked="selected === cat"
      round
      @update:checked="() => emit('change', cat)"
      class="element-filter__tag"
    >
      {{ cat }}
    </NTag>
  </div>
</template>

<style scoped>
.element-filter {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  padding-bottom: var(--spacing-md);
  border-bottom: 1px solid var(--color-border);
}

.element-filter__tag {
  cursor: pointer;
}
</style>
