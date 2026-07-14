import client from './client'
import type { Relation, CreateRelationRequest, UpdateRelationRequest } from '@/types/relation'

export async function listRelations(
  worldId: string,
  characterId?: string
): Promise<Relation[]> {
  const params = characterId ? { character_id: characterId } : undefined
  const { data } = await client.get(`/worlds/${worldId}/relations`, { params })
  return data
}

export async function getRelation(worldId: string, relationId: string): Promise<Relation> {
  const { data } = await client.get(`/worlds/${worldId}/relations/${relationId}`)
  return data
}

export async function createRelation(
  worldId: string,
  req: CreateRelationRequest
): Promise<Relation> {
  const { data } = await client.post(`/worlds/${worldId}/relations`, req)
  return data
}

export async function updateRelation(
  worldId: string,
  relationId: string,
  req: UpdateRelationRequest
): Promise<Relation> {
  const { data } = await client.put(`/worlds/${worldId}/relations/${relationId}`, req)
  return data
}

export async function deleteRelation(worldId: string, relationId: string): Promise<void> {
  await client.delete(`/worlds/${worldId}/relations/${relationId}`)
}
