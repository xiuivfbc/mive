import client from './client'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'

export interface GraphOntology {
  entity_types: string[]
  relation_types: string[]
  constraints?: {
    min_entity_types: number
    max_entity_types: number
    fallback_types: string[]
  }
}

export interface GraphDataResponse {
  characters: Character[]
  relations: Relation[]
  graph_status: 'idle' | 'building' | 'completed' | 'failed'
  graph_ontology: GraphOntology | null
}

export interface GraphTask {
  task_id: string
  task_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  message: string
  result: Record<string, unknown> | null
  error: string | null
}

export interface GraphEntity {
  uuid: string
  name: string
  entity_type: string
  labels: string[]
  summary: string
  attributes: Record<string, unknown>
  related_edges: {
    direction: string
    edge_name: string
    fact: string
    target_node_uuid?: string
    source_node_uuid?: string
  }[]
}

export async function getGraphData(worldId: string): Promise<GraphDataResponse> {
  const { data } = await client.get(`/worlds/${worldId}/graph/data`)
  return data
}

export async function getGraphConfig(worldId: string): Promise<{ zep_available: boolean }> {
  const { data } = await client.get(`/worlds/${worldId}/graph/config`)
  return data
}

export async function generateOntology(
  worldId: string,
  entityTypes?: string[]
): Promise<GraphOntology> {
  const { data } = await client.post(`/worlds/${worldId}/graph/ontology/generate`, {
    entity_types: entityTypes,
  })
  return data
}

export async function buildGraph(
  worldId: string,
  ontology: GraphOntology
): Promise<{ task_id: string }> {
  const { data } = await client.post(`/worlds/${worldId}/graph/build`, { ontology })
  return data
}

export async function getGraphTask(
  worldId: string,
  taskId: string
): Promise<GraphTask> {
  const { data } = await client.get(`/worlds/${worldId}/graph/task/${taskId}`)
  return data
}

export async function getGraphEntities(
  worldId: string,
  entityTypes?: string[],
  enrichWithEdges = false
): Promise<{ entities: GraphEntity[] }> {
  const params: Record<string, string> = {}
  if (entityTypes?.length) params.entity_types = entityTypes.join(',')
  if (enrichWithEdges) params.enrich_with_edges = 'true'
  const { data } = await client.get(`/worlds/${worldId}/graph/entities`, { params })
  return data
}
