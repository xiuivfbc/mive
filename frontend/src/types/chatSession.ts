export interface Participant {
  id: string
  name: string
}

export interface ChatSession {
  id: string
  world_id: string
  type: 'event' | 'character'
  title: string | null
  created_at: string
  last_active_at?: string | null
  participants: Participant[] | null
  participant_mode: 'auto' | 'edit' | 'include' | null
  element_injection_ids?: string[] | null
  constraints?: string
}

export interface ChatSessionListResponse {
  sessions: ChatSession[]
}
