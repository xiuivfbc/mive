import client from './client'

export interface CharacterMemory {
  id: string
  content: string
  session_id: string | null
  created_at: string
  memory_type: 'short_term' | 'long_term'
  // short-term only
  memory_category?: string | null
  short_term_reflection?: string | null
  // long-term only
  event_name?: string | null
  perspective_detail?: string | null
  reflection?: string | null
  involved_characters?: string[] | null
  propagated_from?: string | null
  is_hearsay?: boolean
}

export interface CharacterMemoriesResponse {
  short_term: CharacterMemory[]
  long_term: CharacterMemory[]
}

export function fetchCharacterMemories(worldId: string, characterId: string): Promise<CharacterMemoriesResponse> {
  return client.get(`/worlds/${worldId}/characters/${characterId}/memories`).then(r => r.data)
}

export function deleteCharacterMemory(worldId: string, characterId: string, memoryId: string): Promise<void> {
  return client.delete(`/worlds/${worldId}/characters/${characterId}/memories/${memoryId}`)
}

export function deleteSessionMemories(worldId: string, sessionId: string): Promise<void> {
  return client.delete(`/worlds/${worldId}/sessions/${sessionId}/memories`)
}

export function flushChatMemories(worldId: string, sessionId: string): Promise<void> {
  return client.post(`/worlds/${worldId}/sessions/${sessionId}/flush-memories`)
}

export interface CreateMemoryRequest {
  memory_type: 'short_term' | 'long_term'
  content: string
  memory_category?: string | null
  short_term_reflection?: string | null
  perspective_detail?: string | null
  reflection?: string | null
  event_name?: string | null
  involved_characters?: string[] | null
}

export interface UpdateMemoryRequest {
  content?: string | null
  memory_category?: string | null
  short_term_reflection?: string | null
  perspective_detail?: string | null
  reflection?: string | null
  event_name?: string | null
  involved_characters?: string[] | null
}

export function createCharacterMemory(worldId: string, characterId: string, data: CreateMemoryRequest): Promise<CharacterMemory> {
  return client.post(`/worlds/${worldId}/characters/${characterId}/memories`, data).then(r => r.data)
}

export function updateCharacterMemory(worldId: string, characterId: string, memoryId: string, data: UpdateMemoryRequest): Promise<CharacterMemory> {
  return client.patch(`/worlds/${worldId}/characters/${characterId}/memories/${memoryId}`, data).then(r => r.data)
}
