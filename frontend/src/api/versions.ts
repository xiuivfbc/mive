import client from './client'
import type { WorldVersion } from '@/types/version'

export async function listVersions(worldId: string): Promise<WorldVersion[]> {
  const { data } = await client.get(`/worlds/${worldId}/versions`)
  return data
}

export async function rollbackVersion(
  worldId: string,
  versionId: string
): Promise<WorldVersion> {
  const { data } = await client.post(`/worlds/${worldId}/versions/${versionId}/rollback`)
  return data
}

export async function updateVersionName(
  worldId: string,
  versionId: string,
  summary: string | null
): Promise<WorldVersion> {
  const { data } = await client.patch(`/worlds/${worldId}/versions/${versionId}`, { summary })
  return data
}

export async function deleteVersion(
  worldId: string,
  versionId: string
): Promise<void> {
  await client.delete(`/worlds/${worldId}/versions/${versionId}`)
}

export async function createVersion(worldId: string): Promise<WorldVersion> {
  const { data } = await client.post(`/worlds/${worldId}/versions`)
  return data
}

export async function updateVersionSnapshot(
  worldId: string,
  versionId: string
): Promise<WorldVersion> {
  const { data } = await client.post(`/worlds/${worldId}/versions/${versionId}/update-snapshot`)
  return data
}
