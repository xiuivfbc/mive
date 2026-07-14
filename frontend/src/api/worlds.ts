import client from './client'
import type { WorldDoc, CreateWorldRequest, AddElementRequest, UpdateElementRequest, Element, WorldTemplate, CreateFromTemplateRequest } from '@/types/world'

export async function listWorlds(): Promise<WorldDoc[]> {
  const { data } = await client.get('/worlds')
  return data
}

export async function getWorld(id: string): Promise<WorldDoc> {
  const { data } = await client.get(`/worlds/${id}`)
  return data
}

export interface WikiCandidate {
  url: string
  lang: string | null
  page_title: string | null
  excerpt: string | null
}

export async function checkWiki(title: string, author?: string | null, work_language?: string | null, scale?: string): Promise<{ fast_path: boolean; found: boolean; results: WikiCandidate[]; fast_path_characters?: string[] }> {
  const { data } = await client.post('/worlds/check-wiki', { title, author, work_language, scale })
  return data
}

export interface WikiPreviewResult {
  content: string
  truncated: boolean
}

export async function getWikiPreview(url: string): Promise<WikiPreviewResult> {
  const { data } = await client.post('/worlds/wiki-preview', { url })
  return data
}

export async function createWorld(req: CreateWorldRequest): Promise<{ world_id: string }> {
  const { data } = await client.post('/worlds', req)
  return data
}

export async function getCreationStatus(worldId: string): Promise<{ status: 'creating' | 'ready' | 'failed' }> {
  const { data } = await client.get(`/worlds/${worldId}/creation-status`)
  return data
}

export async function copyWorld(id: string): Promise<WorldDoc> {
  const { data } = await client.post(`/worlds/${id}/copy`)
  return data
}

export async function deleteWorld(id: string): Promise<void> {
  await client.delete(`/worlds/${id}`)
}

export async function generateCharactersAsync(worldId: string, scale?: string): Promise<{ status: string; world_id: string }> {
  const params = scale ? { scale } : undefined
  const { data } = await client.post(`/worlds/${worldId}/generate-characters`, null, { params })
  return data
}

export async function getGenerationStatus(worldId: string): Promise<{ status: string }> {
  const { data } = await client.get(`/worlds/${worldId}/generate-characters/status`)
  return data
}

export async function addElement(worldId: string, req: AddElementRequest): Promise<Element> {
  const { data } = await client.post(`/worlds/${worldId}/elements`, req)
  return data
}

export async function updateElement(worldId: string, elementId: string, req: UpdateElementRequest): Promise<Element> {
  const { data } = await client.put(`/worlds/${worldId}/elements/${elementId}`, req)
  return data
}

export async function deleteElement(worldId: string, elementId: string): Promise<void> {
  await client.delete(`/worlds/${worldId}/elements/${elementId}`)
}

export async function updatePlotSummary(worldId: string, plotSummary: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/plot-summary`, { plot_summary: plotSummary })
}

export async function updateCommonSense(worldId: string, commonSense: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/common-sense`, { common_sense: commonSense })
}

export async function updateCoreConflict(worldId: string, coreConflict: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/core-conflict`, { core_conflict: coreConflict })
}

export async function updateToneAndAtmosphere(worldId: string, toneAndAtmosphere: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/tone-and-atmosphere`, { tone_and_atmosphere: toneAndAtmosphere })
}

export async function updatePlotDevelopment(worldId: string, plotDevelopment: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/plot-development`, { plot_development: plotDevelopment })
}

export async function updateWorldTitle(worldId: string, title: string): Promise<void> {
  await client.patch(`/worlds/${worldId}/title`, { title })
}

export async function listTemplates(): Promise<WorldTemplate[]> {
  const { data } = await client.get('/worlds/templates')
  return data
}

export async function createFromTemplate(req: CreateFromTemplateRequest): Promise<WorldDoc> {
  const { data } = await client.post('/worlds/create-from-template', req)
  return data
}

