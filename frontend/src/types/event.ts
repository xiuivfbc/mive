export interface Event {
  id: string
  world_id: string
  event_type: string
  name: string | null
  description: string | null
  priority: string
  status: string
  is_key_event: boolean
  user_marked: boolean
  created_at: string
  executed_at: string | null
}
