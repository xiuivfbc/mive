import type { CharacterBasic } from './character'
import type { Relation } from './relation'

export interface SnapshotElement {
  name: string
  category: string
  brief: string
  detail: string
}

/** 实体级快照数据（角色 + 关系 + 元素） */
export interface SnapshotData {
  characters: CharacterBasic[]
  relations: Relation[]
  elements?: SnapshotElement[]
}

export interface WorldVersion {
  id: string
  world_id: string
  parent_version_id: string | null
  created_by: string | null
  summary: string | null
  snapshot: SnapshotData
  created_at: string
}
