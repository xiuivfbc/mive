<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useTheme } from '@/composables/useTheme'
const { theme, mode, setTheme, setMode, themes, hasDarkMode } = useTheme()

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

function toggleMode() {
  setMode(mode.value === 'light' ? 'dark' : 'light')
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
  <div ref="containerRef" class="theme-toggle" @mouseenter="open" @mouseleave="close">
    <button class="theme-toggle__btn" type="button" :aria-label="$t('theme.toggleLabel')" :title="$t('theme.toggleLabel')">
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.3"/>
        <circle cx="8" cy="8" r="2" fill="currentColor"/>
        <path d="M8 2v1M8 13v1M2 8h1M13 8h1M3.8 3.8l.7.7M11.5 11.5l.7.7M3.8 12.2l.7-.7M11.5 4.5l.7-.7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
      </svg>
    </button>
    <div class="theme-toggle__menu" :class="{ open: isOpen }" @mouseenter="open" @mouseleave="close">
      <!-- 左侧：亮暗切换 -->
      <button
        class="theme-toggle__mode"
        :class="{ active: mode === 'dark' }"
        type="button"
        :title="mode === 'light' ? $t('theme.mode.dark', '暗') : $t('theme.mode.light', '亮')"
        @click="toggleMode"
      >{{ mode === 'light' ? $t('theme.mode.light', '亮') : $t('theme.mode.dark', '暗') }}</button>
      <!-- 右侧：七色主题 -->
      <div class="theme-toggle__colors">
        <button
          v-for="t in themes"
          :key="t.id"
          class="theme-toggle__option"
          :class="{ active: theme === t.id }"
          type="button"
          @click="setTheme(t.id)"
        >{{ $t('theme.' + t.id) }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.theme-toggle {
  position: relative;
  display: flex;
  align-items: center;
}

/* 图标按钮 */
.theme-toggle__btn {
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
}

.theme-toggle__btn:hover {
  background: var(--accent-hover);
  transform: scale(1.1);
}

/* 下拉菜单 — 双列布局 */
.theme-toggle__menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  display: flex;
  flex-direction: row;
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
}

.theme-toggle__menu.open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
}

/* 左侧：亮暗切换按钮 */
.theme-toggle__mode {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  padding: 5px 0;
  border: none;
  border-radius: 6px;
  background: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  font-family: 'Noto Sans SC', sans-serif;
  writing-mode: vertical-rl;
  letter-spacing: 2px;
}

.theme-toggle__mode:hover {
  color: var(--text-primary);
  background: var(--bg-card);
}

.theme-toggle__mode.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

/* 右侧：七色主题列 */
.theme-toggle__colors {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-toggle__option {
  padding: 5px 18px;
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

.theme-toggle__option:hover {
  color: var(--text-primary);
  background: var(--bg-card);
}

.theme-toggle__option.active {
  color: var(--text-primary);
  background: var(--bg-card);
}

/* BREEZE */
[data-theme="breeze"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="breeze"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* SAKURA */
[data-theme="sakura"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="sakura"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* EMBER */
[data-theme="ember"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="ember"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* SUNFLOWER */
[data-theme="sunflower"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="sunflower"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* OCEAN */
[data-theme="ocean"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="ocean"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* INDIGO */
[data-theme="indigo"] .theme-toggle__menu {
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
[data-theme="indigo"] .theme-toggle__option.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
</style>
