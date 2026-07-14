import client from './client'
import type { Event } from '@/types/event'

export async function pauseStream(worldId: string): Promise<void> {
  await client.post(`/worlds/${worldId}/events/stream/pause`)
}

export async function resumeStream(worldId: string): Promise<void> {
  await client.post(`/worlds/${worldId}/events/stream/resume`)
}

export async function stopStream(worldId: string): Promise<void> {
  await client.post(`/worlds/${worldId}/events/stream/stop`)
}

export interface RewindResult {
  deleted_message_ids: string[]
}

export async function trimStreamMessages(
  worldId: string,
  messageIds: string[]
): Promise<void> {
  await client.post(`/worlds/${worldId}/events/stream/trim`, { message_ids: messageIds })
}

export async function rewindToEvent(
  worldId: string,
  cardMessageId: string
): Promise<RewindResult> {
  const { data } = await client.post(`/worlds/${worldId}/events/stream/rewind`, {
    card_message_id: cardMessageId,
  })
  return data
}

export async function discardEvent(
  worldId: string,
  eventId: string,
  messageIds: string[]
): Promise<void> {
  await client.post(`/worlds/${worldId}/events/${eventId}/discard`, {
    message_ids: messageIds,
  })
}

export async function listEvents(
  worldId: string,
  params?: {
    from_time?: string
    to_time?: string
    status?: string
    event_type?: string
  }
): Promise<Event[]> {
  const { data } = await client.get(`/worlds/${worldId}/events`, { params })
  return data
}

export interface EventIndex {
  id: string
  event_name: string
  brief: string
  dissemination: number
  core_participants: string[]
  created_at: string | null
}

export async function listEventIndex(worldId: string): Promise<EventIndex[]> {
  const { data } = await client.get(`/worlds/${worldId}/events/event-index`)
  return data
}
