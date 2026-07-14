<script setup lang="ts">
import { ref, watch } from 'vue'
import { NModal, NCard, NForm, NFormItem, NInput, NSelect, NButton, NSpace } from 'naive-ui'
import { ELEMENT_CATEGORIES } from '@/types/world'
import type { Element } from '@/types/world'

const props = defineProps<{
  show: boolean
  element: Element | null
  defaultCategory?: string
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  save: [data: { name: string; category: string; brief: string; detail: string }]
}>()

const form = ref({ name: '', category: '', brief: '', detail: '' })
const saving = ref(false)

const categoryOptions = ELEMENT_CATEGORIES.map((c) => ({ label: c, value: c }))

watch(
  () => props.show,
  (v) => {
    if (v) {
      form.value = props.element
        ? { name: props.element.name, category: props.element.category, brief: props.element.brief, detail: props.element.detail }
        : { name: '', category: props.defaultCategory ?? '', brief: '', detail: '' }
      saving.value = false
    }
  },
)

async function handleSave() {
  if (!form.value.name.trim() || !form.value.category) return
  saving.value = true
  try {
    emit('save', { ...form.value })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <NModal :show="show" @update:show="emit('update:show', $event)" :mask-closable="!saving">
    <NCard
      :title="element ? $t('element.editTitle') : $t('element.addTitle')"
      size="small"
      :bordered="false"
      style="width: 480px"
    >
      <NForm label-placement="left" label-width="60" :show-feedback="false">
        <NFormItem :label="$t('element.nameLabel')">
          <NInput v-model:value="form.name" :placeholder="$t('element.namePlaceholder')" />
        </NFormItem>
        <NFormItem :label="$t('element.categoryLabel')">
          <NSelect v-model:value="form.category" :options="categoryOptions" :placeholder="$t('element.categoryPlaceholder')" />
        </NFormItem>
        <NFormItem :label="$t('element.briefLabel')">
          <NInput v-model:value="form.brief" :placeholder="$t('element.briefPlaceholder')" />
        </NFormItem>
        <NFormItem :label="$t('element.detailLabel')">
          <NInput
            v-model:value="form.detail"
            type="textarea"
            :rows="5"
            :placeholder="$t('element.detailPlaceholder')"
          />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="emit('update:show', false)" :disabled="saving">{{ $t('common.cancel') }}</NButton>
          <NButton
            type="primary"
            :loading="saving"
            :disabled="!form.name.trim() || !form.category"
            @click="handleSave"
          >
            {{ $t('common.save') }}
          </NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
:deep(.n-card) {
  border: none;
  border-radius: var(--radius);
}
</style>
