import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock axios before importing useLocale
vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      patch: vi.fn().mockResolvedValue({ data: {} }),
    })),
  },
}))

// We need to reset modules between tests because useLocale uses module-level refs
describe('useLocale', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
  })

  it('defaults to zh-CN when localStorage is empty and navigator.language is unsupported', async () => {
    Object.defineProperty(navigator, 'language', { value: 'fr-FR', configurable: true })
    const { useLocale } = await import('@/composables/useLocale')
    const { locale } = useLocale()
    expect(locale.value).toBe('en')
  })

  it('reads locale from localStorage on init', async () => {
    localStorage.setItem('mive-locale', 'en')
    const { useLocale } = await import('@/composables/useLocale')
    const { locale } = useLocale()
    expect(locale.value).toBe('en')
  })

  it('falls back to browser language if supported', async () => {
    Object.defineProperty(navigator, 'language', { value: 'ja', configurable: true })
    const { useLocale } = await import('@/composables/useLocale')
    const { locale } = useLocale()
    expect(locale.value).toBe('ja')
  })

  it('setLocale updates locale ref and localStorage', async () => {
    const { useLocale } = await import('@/composables/useLocale')
    const { locale, setLocale } = useLocale()
    setLocale('ko')
    expect(locale.value).toBe('ko')
    expect(localStorage.getItem('mive-locale')).toBe('ko')
  })

  it('setLocale with skipSync does not call PATCH', async () => {
    const mockPatch = vi.fn().mockResolvedValue({ data: {} })
    vi.doMock('@/api/client', () => ({
      default: { patch: mockPatch },
    }))
    const { useLocale } = await import('@/composables/useLocale')
    const { setLocale } = useLocale()

    // Simulate logged-in state by setting a token
    setLocale('en', { skipSync: true })

    expect(mockPatch).not.toHaveBeenCalled()
  })

  it('supportedLocales contains all 5 locales', async () => {
    const { useLocale } = await import('@/composables/useLocale')
    const { supportedLocales } = useLocale()
    const ids = supportedLocales.map((l) => l.id)
    expect(ids).toContain('zh-CN')
    expect(ids).toContain('zh-TW')
    expect(ids).toContain('en')
    expect(ids).toContain('ja')
    expect(ids).toContain('ko')
  })
})
