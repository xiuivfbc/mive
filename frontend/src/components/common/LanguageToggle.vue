<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useLocale } from '@/composables/useLocale'
const { locale, setLocale, supportedLocales } = useLocale()

const isOpen = ref(false)
const containerRef = ref<HTMLElement | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | null = null

function open() {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null }
  isOpen.value = true
}

function close() {
  closeTimer = setTimeout(() => { isOpen.value = false }, 80)
}

function handleClickOutside(e: MouseEvent) {
  if (!containerRef.value?.contains(e.target as Node)) isOpen.value = false
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  if (closeTimer) clearTimeout(closeTimer)
})
</script>

<template>
  <div ref="containerRef" class="lang-toggle" @mouseenter="open" @mouseleave="close">
    <button
      class="lang-toggle__btn"
      type="button"
      :aria-label="$t('language.toggleAriaLabel')"
      :title="$t('language.toggleAriaLabel')"
    >
      <span class="lang-toggle__short">{{ supportedLocales.find(l => l.id === locale)?.short ?? 'EN' }}</span>
    </button>
    <div class="lang-toggle__menu" :class="{ open: isOpen }" @mouseenter="open" @mouseleave="close">
      <button
        v-for="l in supportedLocales"
        :key="l.id"
        class="lang-toggle__option"
        :class="{ active: locale === l.id }"
        type="button"
        @click="setLocale(l.id)"
      >{{ l.label }}</button>
    </div>
  </div>
</template>

<style scoped>
.lang-toggle {
  position: relative;
  display: flex;
  align-items: center;
}

.lang-toggle__btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.lang-toggle__btn:hover {
  background: var(--accent-hover);
  transform: scale(1.1);
}

.lang-toggle__short {
  font-family: 'Noto Sans SC', sans-serif;
}

.lang-toggle__menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  border-radius: 10px;
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--bg-deep);
  backdrop-filter: blur(16px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.25);
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.15s;
  pointer-events: none;
  z-index: 100;
  min-width: 110px;
}

.lang-toggle__menu.open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
}

.lang-toggle__option {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: none;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.4px;
  font-family: 'Noto Sans SC', sans-serif;
  text-align: left;
}

.lang-toggle__option:hover {
  color: var(--text-primary);
  background: var(--bg-card);
}

.lang-toggle__option.active {
  color: var(--accent);
  background: var(--bg-card);
}

/* BREEZE */
[data-theme="breeze"] .lang-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}

</style>
