/**
 * Generate a letter code for a given index.
 * 0 → 'a', 1 → 'b', ..., 25 → 'z', 26 → 'aa', 27 → 'ab', etc.
 */
export function genCode(i: number): string {
  const a = 'abcdefghijklmnopqrstuvwxyz'
  return i < 26 ? a[i] : a[Math.floor((i - 26) / 26)] + a[(i - 26) % 26]
}
