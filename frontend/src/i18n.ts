import { createI18n } from 'vue-i18n'
import zhCN from '@/locales/zh-CN'
import zhTW from '@/locales/zh-TW'
import en from '@/locales/en'
import ja from '@/locales/ja'
import ko from '@/locales/ko'
import { _registerI18nLocale, detectInitialLocale } from '@/composables/useLocale'

// Use the same initial locale detection as useLocale
const initialLocale = detectInitialLocale()

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'zh-TW': zhTW,
    en,
    ja,
    ko,
  },
})

// Register so setLocale() can drive i18n without circular imports
_registerI18nLocale(i18n.global.locale as { value: string })
