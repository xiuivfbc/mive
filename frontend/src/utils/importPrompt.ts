export function extractPromptSection(md: string, locale: string): string {
  const isZh = locale.startsWith('zh')
  const targetHeading = isZh ? '简体中文' : 'English'

  // Split on ## headings
  const parts = md.split(/\n(?=## )/)
  for (const part of parts) {
    if (part.startsWith(`## ${targetHeading}`)) {
      return part
        .replace(/^## .+\n+/, '')
        .replace(/\n---\n[\s\S]*$/, '')
        .trim()
    }
  }

  return md
}
