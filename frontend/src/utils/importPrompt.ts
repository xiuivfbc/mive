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

/**
 * Extract the first JSON block from text that may contain markdown code fences
 * or surrounding explanatory text.
 */
export function extractFirstJsonBlock(text: string): string {
  const trimmed = text.trim()

  // Strategy 1: Look for ```json or ``` code blocks
  const fenceRegex = /```(?:json)?\s*\n?([\s\S]*?)```/g
  const fenceMatches = [...trimmed.matchAll(fenceRegex)]
  if (fenceMatches.length > 0) {
    for (const m of fenceMatches) {
      const content = m[1].trim()
      if (content) return content
    }
  }

  // Strategy 2: Find the outermost { ... } or [ ... ] by depth tracking
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i]
    if (ch === '{' || ch === '[') {
      const endChar = ch === '{' ? '}' : ']'
      let depth = 1
      let start = i
      i++
      while (i < trimmed.length && depth > 0) {
        if (trimmed[i] === ch || trimmed[i] === endChar) {
          if (trimmed[i] === ch) depth++
          else depth--
        }
        i++
      }
      if (depth === 0) {
        return trimmed.slice(start, i)
      }
    }
  }

  return trimmed
}

/**
 * Extract all JSON blocks from text that may contain markdown code fences.
 */
export function extractJsonBlocks(text: string): string[] {
  const blocks: string[] = []
  const trimmed = text.trim()

  const inCode = trimmed.includes('```')
  if (inCode) {
    const codeMatches = trimmed.match(/```(?:json)?\s*\n?([\s\S]*?)```/g)
    if (codeMatches) {
      for (const match of codeMatches) {
        const content = match.replace(/^```(?:json)?\s*\n?/, '').replace(/\s*```$/, '').trim()
        if (content) blocks.push(content)
      }
    }
  }

  if (blocks.length === 0) {
    for (let i = 0; i < trimmed.length; i++) {
      const ch = trimmed[i]
      if (ch === '{' || ch === '[') {
        const endChar = ch === '{' ? '}' : ']'
        let depth = 1
        let start = i
        i++
        while (i < trimmed.length && depth > 0) {
          if (trimmed[i] === ch) depth++
          else if (trimmed[i] === endChar) depth--
          i++
        }
        if (depth === 0) blocks.push(trimmed.slice(start, i))
      }
    }
  }

  return blocks
}
