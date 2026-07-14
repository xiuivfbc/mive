import client from './client'
import type { Character, CreateCharacterRequest, UpdateCharacterRequest } from '@/types/character'

export async function listCharacters(worldId: string): Promise<Character[]> {
  const { data } = await client.get(`/worlds/${worldId}/characters`)
  return data
}

export async function getCharacter(worldId: string, characterId: string): Promise<Character> {
  const { data } = await client.get(`/worlds/${worldId}/characters/${characterId}`)
  return data
}

export async function createCharacter(
  worldId: string,
  req: CreateCharacterRequest
): Promise<Character> {
  const { data } = await client.post(`/worlds/${worldId}/characters`, req)
  return data
}

export async function updateCharacter(
  worldId: string,
  characterId: string,
  req: UpdateCharacterRequest
): Promise<Character> {
  const { data } = await client.put(`/worlds/${worldId}/characters/${characterId}`, req)
  return data
}

export async function deleteCharacter(worldId: string, characterId: string): Promise<void> {
  await client.delete(`/worlds/${worldId}/characters/${characterId}`)
}

export async function generateCharacters(worldId: string, scale?: string): Promise<{ characters: number; relations: number }> {
  const params = scale ? { scale } : undefined
  const { data } = await client.post(`/worlds/${worldId}/characters/generate`, null, { params })
  return data
}
