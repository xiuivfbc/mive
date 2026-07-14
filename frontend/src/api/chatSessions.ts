import client from './client'
import type { ChatSessionListResponse } from '@/types/chatSession'
import type { Message } from '@/types/message'

export async function listChatSessions(worldId: string): Promise<ChatSessionListResponse> {
  const { data } = await client.get(`/worlds/${worldId}/chat-sessions`)
  return data
}

export async function getChatSessionMessages(
  worldId: string,
  sessionId: string
): Promise<{ messages: Message[] }> {
  const { data } = await client.get(`/worlds/${worldId}/chat-sessions/${sessionId}/messages`)
  return data
}

export async function deleteChatSession(worldId: string, sessionId: string): Promise<void> {
  await client.delete(`/worlds/${worldId}/chat-sessions/${sessionId}`)
}
