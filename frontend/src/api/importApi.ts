import client from './client'

// ── World fields import ─────────────────────────────────────────────────────

interface WorldFieldPreviewEntry {
  old: string
  new: string
  merged: string
  strategy: 'overwrite' | 'append' | 'skip'
}

export interface WorldFieldsPreviewResponse {
  world_fields: Record<string, WorldFieldPreviewEntry>
}

export async function previewWorldFields(
  worldId: string,
  data: Record<string, string>,
  strategies?: Record<string, string>,
): Promise<WorldFieldsPreviewResponse> {
  const { data: resp } = await client.post(`/worlds/${worldId}/import/preview-world-fields`, {
    data,
    strategies: strategies ?? {},
  })
  return resp
}

export async function confirmWorldFields(
  worldId: string,
  data: Record<string, string>,
  strategies?: Record<string, string>,
): Promise<void> {
  await client.post(`/worlds/${worldId}/import/world-fields`, {
    data,
    strategies: strategies ?? {},
  })
}

// ── Graph (characters + relations) import ────────────────────────────────────

export interface ImportCharacterPreview {
  index: number
  id: string | null
  name: string
  tier: string
  brief: string
  detail: string
  personality: string
  speech_style: string
  status: 'new' | 'existing' | 'duplicate_in_batch'
}

export interface ImportRelationPreview {
  character_a: string
  character_b: string
  resolved_a: string | null
  resolved_b: string | null
  type: string | null
  description: string | null
  direction: string
  status: 'valid' | 'skipped'
}

export interface GraphPreviewResponse {
  characters: ImportCharacterPreview[]
  relations: ImportRelationPreview[]
  new_characters: number
  existing_characters: number
  valid_relations: number
  skipped_relations: number
}

export interface ImportCharacterReq {
  name: string
  tier: string
  brief: string
  detail: string
  personality: string
  speech_style: string
}

export interface ImportRelationReq {
  character_a: string
  character_b: string
  type?: string | null
  description?: string | null
  direction?: string
}

export interface GraphConfirmRequest {
  characters: ImportCharacterReq[]
  relations: ImportRelationReq[]
}

export async function previewGraphImport(
  worldId: string,
  characters: ImportCharacterReq[],
  relations: ImportRelationReq[],
): Promise<GraphPreviewResponse> {
  const { data } = await client.post(`/worlds/${worldId}/import/preview-graph`, {
    characters,
    relations,
  })
  return data
}

export async function confirmGraphImport(
  worldId: string,
  characters: ImportCharacterReq[],
  relations: ImportRelationReq[],
): Promise<{ characters: number; relations: number }> {
  const { data } = await client.post(`/worlds/${worldId}/import/graph`, {
    characters,
    relations,
  })
  return data
}

// ── Elements import ──────────────────────────────────────────────────────────

export interface ImportElementPreview {
  name: string
  category: string
  brief: string
  detail: string
  status: 'new' | 'existing'
}

export interface ElementsPreviewResponse {
  elements: ImportElementPreview[]
  new_elements: number
  existing_elements: number
}

export interface ImportElementReq {
  name: string
  category: string
  brief: string
  detail: string
}

export async function previewElementsImport(
  worldId: string,
  elements: ImportElementReq[],
): Promise<ElementsPreviewResponse> {
  const { data } = await client.post(`/worlds/${worldId}/import/preview-elements`, {
    elements,
  })
  return data
}

export async function confirmElementsImport(
  worldId: string,
  elements: ImportElementReq[],
): Promise<{ created: number }> {
  const { data } = await client.post(`/worlds/${worldId}/import/elements`, {
    elements,
  })
  return data
}
