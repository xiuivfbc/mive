import client from './client'

export interface AdminConfigItem {
  key: string
  value: string
  source: 'override' | 'env_default'
}

export interface AdminConfigGroupResponse {
  group: string
  items: AdminConfigItem[]
}

export async function getConfigGroup(group: string): Promise<AdminConfigGroupResponse> {
  const { data } = await client.get(`/admin/config/${group}`)
  return data
}

export async function updateConfigGroup(group: string, values: Record<string, string>): Promise<AdminConfigGroupResponse> {
  const { data } = await client.put(`/admin/config/${group}`, { values })
  return data
}

export async function resetConfigGroup(group: string): Promise<AdminConfigGroupResponse> {
  const { data } = await client.delete(`/admin/config/${group}`)
  return data
}
