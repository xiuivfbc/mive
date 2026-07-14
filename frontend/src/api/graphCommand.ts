import apiClient from './client'

export interface GraphOperation {
  op: 'add_character' | 'add_relation' | 'delete_relation' | 'update_relation' | 'delete_character' | 'update_character'
  // add_character
  name?: string
  tier?: string
  gender?: string
  age?: number | null
  occupation?: string
  brief?: string
  // add/delete/update_relation
  character_a?: string
  character_b?: string
  type?: string
  description?: string
  direction?: string
  // update_*
  changes?: Record<string, unknown>
}

export interface ParseResult {
  operations: GraphOperation[]
  summary: string
}

export interface ApplyResult {
  added_chars: string[]
  added_rels: string[]
  deleted_rels: string[]
  updated_rels: string[]
  errors: string[]
}

export async function parseCommand(worldId: string, command: string): Promise<ParseResult> {
  const res = await apiClient.post(`/worlds/${worldId}/graph-command/parse`, { command })
  return res.data
}

export async function applyCommand(worldId: string, operations: GraphOperation[]): Promise<ApplyResult> {
  const res = await apiClient.post(`/worlds/${worldId}/graph-command/apply`, { operations })
  return res.data
}
