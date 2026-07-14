import client from './client'

export interface WelcomeQuote {
  id: string
  user_id: string
  username: string
  content: string
  status: string
  ai_verdict?: string | null
  ai_reason?: string | null
  created_at: string
}

export async function listWelcomeQuotes(): Promise<WelcomeQuote[]> {
  const { data } = await client.get('/welcome-quotes')
  return data
}

export async function createWelcomeQuote(content: string): Promise<WelcomeQuote> {
  const { data } = await client.post('/welcome-quotes', { content })
  return data
}

export async function getMyQuotes(): Promise<WelcomeQuote[]> {
  const { data } = await client.get('/welcome-quotes/mine')
  return data
}

export async function deleteWelcomeQuote(id: string): Promise<void> {
  await client.delete(`/welcome-quotes/${id}`)
}

export async function checkEligibility(): Promise<{ eligible: boolean }> {
  const { data } = await client.get('/welcome-quotes/eligibility')
  return data
}

// Admin
export async function listAdminQuotes(status?: string): Promise<WelcomeQuote[]> {
  const { data } = await client.get('/admin/welcome-quotes', { params: { status } })
  return data
}

export async function updateQuoteStatus(id: string, status: string): Promise<void> {
  await client.patch(`/admin/welcome-quotes/${id}`, { status })
}
