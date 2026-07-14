export type MessageType = 'dialogue' | 'narration' | 'system' | 'user' | 'event'
export type SenderType = 'character' | 'narrator' | 'system' | 'user'

export interface Message {
  id: string
  world_id: string
  type: MessageType
  sender_type: SenderType
  sender_id: string | null
  sender_name: string | null
  content: string
  real_time: string | null
  is_key_message: boolean
  user_participated: boolean
  created_at: string | null
  sequence?: number | null
  status?: 'normal' | 'failed'
}

// Import into local scope (used below) and re-export for consumers
import type { Participant } from './chatSession'
export type { Participant }

export interface SendMessageRequest {
  content: string
  participant_mode?: 'auto' | 'edit' | 'include'
  participants?: Participant[] | null
  session_id?: string | null
  memories_enabled?: boolean
  action_descriptions?: boolean
  show_narration?: boolean
  element_rerank?: boolean
  idempotency_key?: string | null
  element_injection_ids?: string[] | null
  constraint?: string | null
}

/** Queue item for the message queue system */
export interface QueueItem {
  id: string
  idempotencyKey: string
  content: string
  senderType: 'user'
  participantMode: 'auto' | 'edit' | 'include'
  participants: Participant[] | null
  /** User role character id selected at the moment this item was enqueued (null = explorer) */
  userRole: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  createdAt: number
  retryCount: number
}

/** Shape stored in localStorage for queue persistence */
export interface QueuePersistData {
  worldId: string
  sessionId: string | null
  pendingQueue: QueueItem[]
  processingItem: QueueItem | null
}

export interface SendMessageResponse {
  user_message: Message
  responses: Message[]
  narration: Message | null
  error: string | null
  session_id: string | null
  participants: Participant[]
  participant_mode: 'auto' | 'edit' | 'include'
  memory_flush_triggered?: boolean
}

export interface MessageListResponse {
  messages: Message[]
  has_more: boolean
}

export interface EventCard {
  title: string
  description: string
  participants: string[]
}

export interface SseEventInjectedPayload {
  event_id: string
  card_message_id: string
  title: string
  description: string
  participants: string[]
  card_message_sequence?: number | null
  session_id?: string | null
}

export interface SseSpeakerTurnPayload {
  id: string
  sender_name: string
  sender_id: string | null
  content: string
  sequence?: number | null
}

export interface SseNarratorTurnPayload {
  id: string
  content: string
  sequence?: number | null
}
