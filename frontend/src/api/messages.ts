import client from './client'
import type { Message, SendMessageResponse, MessageListResponse } from '@/types/message'
import type { Participant } from '@/types/chatSession'

export async function listMessages(
  worldId: string,
  params?: {
    before_sequence?: number
    limit?: number
    sender_id?: string
    type?: string
    session_id?: string
  }
): Promise<MessageListResponse> {
  const { data } = await client.get(`/worlds/${worldId}/messages`, { params })
  return data
}

export async function sendMessage(
  worldId: string,
  content: string,
  participantMode: 'auto' | 'edit' | 'include' = 'auto',
  participants?: Participant[] | null,
  sessionId?: string | null,
  memoriesEnabled?: boolean,
  actionDescriptions: boolean = false,
  elementRerank: boolean = false,
  idempotencyKey?: string | null,
  showNarration: boolean = false,
  userRole?: string | null,
  elementInjectionIds?: string[] | null,
  constraint?: string | null,
): Promise<SendMessageResponse> {
  const body: Record<string, unknown> = { content, participant_mode: participantMode }
  if (participants !== undefined && participants !== null) {
    body.participants = participants
  }
  if (sessionId) body.session_id = sessionId
  if (memoriesEnabled !== undefined) body.memories_enabled = memoriesEnabled
  body.action_descriptions = actionDescriptions
  body.show_narration = showNarration
  body.element_rerank = elementRerank
  if (idempotencyKey) body.idempotency_key = idempotencyKey
  if (userRole) body.user_role = userRole
  if (elementInjectionIds !== undefined && elementInjectionIds !== null) {
    body.element_injection_ids = elementInjectionIds
  }
  if (constraint) body.constraint = constraint
  const { data } = await client.post(`/worlds/${worldId}/messages`, body)
  return data
}
