import { ref } from 'vue'

export type Locale = 'zh-CN' | 'zh-TW' | 'en' | 'ja' | 'ko'

export interface LocaleMeta {
  id: Locale
  label: string
  short: string
}

const STORAGE_KEY = 'mive-locale'
const SUPPORTED: Locale[] = ['zh-CN', 'zh-TW', 'en', 'ja', 'ko']

export const supportedLocales: LocaleMeta[] = [
  { id: 'zh-CN', label: '简体中文', short: '简' },
  { id: 'zh-TW', label: '繁體中文', short: '繁' },
  { id: 'en', label: 'English', short: 'EN' },
  { id: 'ja', label: '日本語', short: '日' },
  { id: 'ko', label: '한국어', short: '한' },
]

export function detectInitialLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY) as Locale | null
  if (stored && SUPPORTED.includes(stored)) return stored
  const browserLang = navigator.language
  // 精确匹配优先（zh-TW → zh-TW），再按 script subtag 匹配（zh-Hant → zh-TW），最后按语言前缀
  return (
    SUPPORTED.find((l) => browserLang === l) ??
    (browserLang.startsWith('zh-Hant') ? 'zh-TW' : null) ??
    SUPPORTED.find((l) => browserLang.startsWith(l.split('-')[0])) ??
    'en'
  )
}

const currentLocale = ref<Locale>(detectInitialLocale())

// Lazy reference to i18n instance to avoid circular imports and test issues
let _i18nGlobalLocale: { value: string } | null = null

export function _registerI18nLocale(localeRef: { value: string }) {
  _i18nGlobalLocale = localeRef
}

export interface SetLocaleOptions {
  skipSync?: boolean
}

export function useLocale() {
  function setLocale(lang: Locale, options: SetLocaleOptions = {}) {
    currentLocale.value = lang
    localStorage.setItem(STORAGE_KEY, lang)
    if (_i18nGlobalLocale) {
      _i18nGlobalLocale.value = lang
    }
    // Update HTML lang attribute for accessibility and browser features
    document.documentElement.lang = lang

    if (!options.skipSync) {
      _syncToBackend(lang)
    }
  }

  return { locale: currentLocale, setLocale, supportedLocales }
}

function _syncToBackend(lang: Locale) {
  // Backend sync removed in open source version
  // Language preference is stored in localStorage only
}
