import client from './client'

export interface GuideData {
  all_content: string
  recent_content: string
  recent_updated_at: string | null
  context_help: string
}

export async function getGuide(): Promise<GuideData> {
  const res = await client.get('/guide')
  return res.data
}
