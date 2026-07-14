export interface Element {
  id: string
  category: string
  name: string
  brief: string
  detail: string
}

export interface WorldSource {
  title: string | null
  author: string | null
  type: string | null
  references: string[]
  input_text: string | null
  detected_work_type: string | null
  source_urls: string[]
  sub_source_urls?: string[]
  wiki_text: string | null
  wiki_characters: string | null
  wiki_plot: string | null
  wiki_world_setting: string | null
  plot_summary: string | null
  common_sense: string | null
  core_conflict: string | null
  tone_and_atmosphere: string | null
  plot_development: string | null
}

export interface WorldMeta {
  created_at: string
  updated_at: string
  last_analyzed_at: string | null
}

export interface WorldDoc {
  world_id: string
  world_base_id: string | null
  version: string
  source: WorldSource
  meta: WorldMeta
  elements: Element[]
  element_count?: number
  character_count?: number
  relationship_count?: number
  user_character_id?: string | null
  scale?: string
}

export interface IdentifyWorkRequest {
  title: string
  author?: string | null
  description?: string | null
}

export interface WorkCandidate {
  name: string
  description: string
}

export interface IdentifyWorkResponse {
  type: 'single' | 'ambiguous'
  work_type?: string | null
  candidates?: WorkCandidate[]
}

export interface CreateWorldRequest {
  title: string
  author?: string | null
  type?: string | null
  description?: string | null
  urls?: string[]
  scale?: string
  detected_work_type?: string | null
  confirmed_wiki_url?: string | null
  fast_path?: boolean
  fast_path_characters?: string[]
}

export interface UpdateElementRequest {
  name: string
  category: string
  brief: string
  detail: string
}

export const ELEMENT_CATEGORIES = ['场所', '势力', '规则', '事件', '物品', '文化', '其他'] as const
export type ElementCategory = (typeof ELEMENT_CATEGORIES)[number]

const CATEGORY_KEYWORD_MAP: Array<[ElementCategory, string[]]> = [
  ['场所', ['场所', '地理', '地点', '区域', '建筑', '地标', '环境']],
  ['势力', ['势力', '阵营', '组织', '国家', '团体', '派系', '门派', '帮派']],
  ['规则', ['规则', '规律', '法则', '设定', '体系', '法术', '武功', '能力', '技能', '科技', '魔法', '系统']],
  ['事件', ['事件', '历史事件', '战役', '战争', '事故', '危机']],
  ['物品', ['物品', '道具', '法宝', '神器', '装备', '宝物', '器物', '武器']],
  ['文化', ['文化', '风俗', '习俗', '宗教', '历史', '背景', '制度', '社会', '语言', '信仰']],
]

export function normalizeCategory(category: string): ElementCategory {
  const exact = ELEMENT_CATEGORIES.find((c) => c === category)
  if (exact) return exact
  for (const [fixed, keywords] of CATEGORY_KEYWORD_MAP) {
    if (keywords.some((kw) => category.includes(kw))) return fixed
  }
  return '其他'
}

export interface AddElementRequest {
  category: string
  name: string
  brief: string
  detail: string
}

export interface WorldTemplate {
  id: string
  title: string
  category: string
  description: string
  element_count: number
}

export interface CreateFromTemplateRequest {
  template_id: string
  scale?: 'standard' | 'detailed' | 'deep' | 'all'
}

