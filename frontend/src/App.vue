<template>
  <!-- background decoration blobs -->
  <div class="bg-decor" aria-hidden="true">
    <div class="bg-blob bg-blob--a" />
    <div class="bg-blob bg-blob--b" />
    <div class="bg-blob bg-blob--c" />
  </div>
  <n-config-provider
    :theme-overrides="naiveThemeOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
  >
    <n-notification-provider>
      <n-message-provider>
        <n-dialog-provider>
          <router-view />
          <div v-if="!isWelcome" class="global-toolbar">
            <div class="global-toolbar__inner">
              <GuideButton @click="showGuide = true" />
              <LanguageToggle />
              <ThemeToggle />
            </div>
          </div>
          <GuideModal
            v-model:show="showGuide"
            :all-content="guideAllContent"
            :recent-content="guideRecentContent"
            :context-help="guideContextHelp"
            @update:show="handleGuideClose"
          />
        </n-dialog-provider>
      </n-message-provider>
    </n-notification-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  zhCN, dateZhCN,
  zhTW, dateZhTW,
  enUS, dateEnUS,
  jaJP, dateJaJP,
  koKR, dateKoKR,
  createDiscreteApi,
} from 'naive-ui'
import { useNaiveTheme } from '@/composables/useNaiveTheme'
import { useLocale } from '@/composables/useLocale'
import { useMouseGlow } from '@/composables/useMouseGlow'
import { useAuthStore } from '@/stores/auth'
import { getGuide } from '@/api/guide'
import type { GuideData } from '@/api/guide'
import GuideButton from '@/components/guide/GuideButton.vue'
import GuideModal from '@/components/guide/GuideModal.vue'
import LanguageToggle from '@/components/common/LanguageToggle.vue'
import ThemeToggle from '@/components/common/ThemeToggle.vue'

useMouseGlow()

const showGuide = ref(false)
const authStore = useAuthStore()
const route = useRoute()
const { t } = useI18n()
const isWelcome = computed(() => route.name === 'Welcome')
const isChat = computed(() => route.name === 'Chat')

// Guide content for version check + modal props
const guideAllContent = ref('')
const guideRecentContent = ref('')
const guideContextHelp = ref('{}')

const _GUIDE_LAST_SEEN_KEY = 'guideLastSeen'

const guideRecentUpdatedAt = ref<string | null>(null)

async function checkGuideUpdate() {
  try {
    const data: GuideData = await getGuide()
    guideAllContent.value = data.all_content
    guideRecentContent.value = data.recent_content
    guideContextHelp.value = data.context_help ?? '{}'
    guideRecentUpdatedAt.value = data.recent_updated_at ?? null

    // No recent content published yet — don't show
    if (!data.recent_updated_at) return

    const lastSeen = localStorage.getItem(_GUIDE_LAST_SEEN_KEY)
    if (lastSeen !== data.recent_updated_at) {
      showGuide.value = true
    }
  } catch {
    // Silent fail — guide check is non-critical
  }
}

function handleGuideClose(val: boolean) {
  showGuide.value = val
  if (!val && guideRecentUpdatedAt.value) {
    localStorage.setItem(_GUIDE_LAST_SEEN_KEY, guideRecentUpdatedAt.value)
  }
}

onMounted(async () => {
  await authStore.initialize()
  await checkGuideUpdate()
})

const { naiveThemeOverrides } = useNaiveTheme()
const { locale } = useLocale()

function showMessage(type: 'info' | 'success' | 'error', content: string, duration = 3000) {
  const { message } = createDiscreteApi(['message'], {
    configProviderProps: { themeOverrides: naiveThemeOverrides.value },
  })
  message[type](content, { duration })
}

const naiveLocaleMap = {
  'zh-CN': zhCN,
  'zh-TW': zhTW,
  en: enUS,
  ja: jaJP,
  ko: koKR,
} as const

const naiveDateLocaleMap = {
  'zh-CN': dateZhCN,
  'zh-TW': dateZhTW,
  en: dateEnUS,
  ja: dateJaJP,
  ko: dateKoKR,
} as const

const naiveLocale = computed(() => naiveLocaleMap[locale.value])
const naiveDateLocale = computed(() => naiveDateLocaleMap[locale.value])
</script>

<style scoped>
.global-nav {
  position: fixed;
  top: 12px;
  left: 16px;
  z-index: 200;
  pointer-events: all;
}

.global-nav__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius);
}

.global-toolbar {
  position: fixed;
  top: 12px;
  right: 16px;
  z-index: 200;
  pointer-events: all;
}

.global-toolbar__inner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius);
}

@media (max-width: 1024px) {
  .global-nav {
    top: 8px;
    left: 8px;
  }

  .global-nav__inner {
    flex-direction: row;
    gap: 4px;
    padding: 4px 8px;
  }

  .global-nav__inner :deep(.n-button) {
    padding: 0 !important;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .global-nav__inner :deep(.n-button__icon) {
    margin: 0 !important;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .global-nav__inner :deep(.n-button__content) {
    display: none !important;
  }

  .nav-btn-text {
    display: none;
  }

  .global-toolbar {
    top: 12px;
    right: 16px;
  }
}
</style>
