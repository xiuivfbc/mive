export interface Relation {
  id: string
  world_id: string
  character_a: string
  character_b: string
  type: string | null
  direction: string
  description: string | null
  status: string
  historical_changes: Record<string, unknown>[] | null
  graph_edge_uuid?: string | null
  created_at: string
  updated_at: string
}

export interface CreateRelationRequest {
  character_a: string
  character_b: string
  type?: string | null
  direction?: string
  description?: string | null
}

export interface UpdateRelationRequest {
  type?: string | null
  direction?: string | null
  description?: string | null
  status?: string | null
}
