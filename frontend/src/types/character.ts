export interface CharacterBasic {
  id: string
  name?: string | null
  tier?: 'core' | 'supporting' | 'extra' | null
}

export interface CharacterProfile {
  basic?: CharacterBasic
  brief?: string
  detail?: string
  personality?: string
  speech_style?: string
  [key: string]: unknown
}

export interface Character {
  id: string
  world_id: string
  name: string
  portrait_url: string | null
  profile: CharacterProfile
  graph_node_uuid?: string | null
  entity_type?: string
  tier?: 'core' | 'supporting' | 'extra' | null
  created_at: string
  updated_at: string
}

export interface CreateCharacterRequest {
  name: string
  portrait_url?: string | null
  profile?: CharacterProfile | null
}

export interface UpdateCharacterRequest {
  name?: string | null
  portrait_url?: string | null
  profile?: CharacterProfile | null
  tier?: string | null
}
