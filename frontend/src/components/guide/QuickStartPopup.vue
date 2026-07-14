<template>
  <n-modal :show="show" :auto-focus="false">
    <n-card
      title="快速上手"
      :bordered="true"
      size="huge"
      style="max-width: 420px; width: 90vw"
      :segmented="{ content: true, footer: true }"
    >
      <div class="quickstart-steps">
        <div class="quickstart-step">
          <span class="quickstart-step__emoji">🎭</span>
          <div>
            <div class="quickstart-step__title">选个模板创建世界</div>
            <div class="quickstart-step__desc">在「我的世界」页面点击「从模板创建」，选择喜欢的世界观</div>
          </div>
        </div>
        <div class="quickstart-step">
          <span class="quickstart-step__emoji">💬</span>
          <div>
            <div class="quickstart-step__title">和角色聊天</div>
            <div class="quickstart-step__desc">进入世界后点击「开始聊天」，发送第一条消息</div>
          </div>
        </div>
        <div class="quickstart-step">
          <span class="quickstart-step__emoji">📖</span>
          <div>
            <div class="quickstart-step__title">遇到问题？</div>
            <div class="quickstart-step__desc">随时点击右上角 ❓ 查看完整指南</div>
          </div>
        </div>
      </div>
      <template #footer>
        <div style="text-align: center">
          <n-button type="primary" @click="emit('close')">知道了</n-button>
        </div>
      </template>
    </n-card>
  </n-modal>
</template>

<script setup lang="ts">
import { NButton, NCard, NModal } from 'naive-ui'

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  close: []
}>()
</script>

<style scoped>
.quickstart-steps {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.quickstart-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.quickstart-step__emoji {
  font-size: 24px;
  flex-shrink: 0;
  line-height: 1.4;
}

.quickstart-step__title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 2px;
}

.quickstart-step__desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}
</style>
