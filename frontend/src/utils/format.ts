/**
 * Format a token count for display.
 * - >= 1,000,000 → "1.2M"
 * - >= 1,000     → "30k"
 * - otherwise    → raw number string
 */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}
