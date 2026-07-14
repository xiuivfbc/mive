<template>
  <div class="page-header">
    <div class="page-header__left">
      <div class="page-header__accent" />
      <div>
        <h1 class="page-header__title">
          <slot name="title-prefix" />{{ title }}<slot name="title-suffix" />
        </h1>
        <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div class="page-header__actions">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-2xl) 0 var(--spacing-lg);
  position: relative;
}

.page-header::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-dim) 40%, transparent 80%);
  opacity: 0.5;
}

.page-header__left {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.page-header__accent {
  width: 4px;
  height: 36px;
  border-radius: 2px;
  background: var(--gradient-accent);
  flex-shrink: 0;
  box-shadow: 0 0 12px var(--accent-glow);
}

.page-header__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  line-height: 1.2;
}

.page-header__subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.page-header__actions {
  display: flex;
  gap: var(--spacing-sm);
}
</style>
