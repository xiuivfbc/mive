import { ref, watch } from 'vue'

export type Theme = 'ink' | 'breeze' | 'sakura' | 'ember' | 'sunflower' | 'ocean' | 'indigo'
export type ThemeMode = 'light' | 'dark'

export interface ThemeMeta {
  id: Theme
  label: string
}

const STORAGE_KEY = 'mive-theme-v2'
const MODE_STORAGE_KEY = 'mive-theme-mode'

const RAINBOW_THEMES: Theme[] = ['sakura', 'ember', 'sunflower', 'ink', 'ocean', 'indigo', 'breeze']

/** 哪些主题有暗色模式 */
export const themesWithDark: ReadonlySet<Theme> = new Set<Theme>(['ink', 'breeze', 'sakura', 'ember', 'sunflower', 'ocean', 'indigo'])

function randomRainbow(): Theme {
  return RAINBOW_THEMES[Math.floor(Math.random() * RAINBOW_THEMES.length)]
}

export const themes: ThemeMeta[] = [
  { id: 'sakura', label: '红' },
  { id: 'ember', label: '橙' },
  { id: 'sunflower', label: '黄' },
  { id: 'ink', label: '绿' },
  { id: 'ocean', label: '蓝' },
  { id: 'indigo', label: '靛' },
  { id: 'breeze', label: '紫' },
]

const currentTheme = ref<Theme>(loadTheme())
const currentMode = ref<ThemeMode>(loadMode())

function loadTheme(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'ink' || saved === 'breeze' || saved === 'sakura' || saved === 'ember' || saved === 'sunflower' || saved === 'ocean' || saved === 'indigo') return saved
  const picked = randomRainbow()
  localStorage.setItem(STORAGE_KEY, picked)
  return picked
}

function loadMode(): ThemeMode {
  const saved = localStorage.getItem(MODE_STORAGE_KEY)
  if (saved === 'dark') return 'dark'
  return 'light'
}

function applyTheme(theme: Theme, mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.setAttribute('data-mode', themesWithDark.has(theme) ? mode : 'light')
}

// Apply immediately on module load
applyTheme(currentTheme.value, currentMode.value)

watch(currentTheme, (t) => {
  applyTheme(t, currentMode.value)
  localStorage.setItem(STORAGE_KEY, t)
})

watch(currentMode, (m) => {
  applyTheme(currentTheme.value, m)
  localStorage.setItem(MODE_STORAGE_KEY, m)
})

export function useTheme() {
  function setTheme(t: Theme) {
    currentTheme.value = t
    // 切换到没有暗色模式的主题时，自动回到亮色
    if (!themesWithDark.has(t)) currentMode.value = 'light'
  }

  function setMode(m: ThemeMode) {
    if (themesWithDark.has(currentTheme.value)) currentMode.value = m
  }

  function hasDarkMode(t: Theme): boolean {
    return themesWithDark.has(t)
  }

  function toggle() {
    const idx = themes.findIndex((t) => t.id === currentTheme.value)
    currentTheme.value = themes[(idx + 1) % themes.length].id
  }

  return { theme: currentTheme, mode: currentMode, setTheme, setMode, toggle, themes, hasDarkMode }
}
