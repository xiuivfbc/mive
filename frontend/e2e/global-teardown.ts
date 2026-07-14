export default async function globalTeardown() {
  try {
    await fetch('http://127.0.0.1:8000/api/e2e/cleanup', { method: 'DELETE' })
  } catch {
    // Backend may already be down — ignore
  }
}
