import { ref, readonly } from 'vue'

// 彩虹七色：高饱和度、差异明显
const RAINBOW_7 = [
  '#FF4444', // 红
  '#FF8C00', // 橙
  '#FFD700', // 黄
  '#00CC66', // 绿
  '#00CCCC', // 青
  '#4488FF', // 蓝
  '#AA44FF', // 紫
]

// 会话级颜色映射（角色名 → 颜色）
const colorMap = ref<Map<string, string>>(new Map())
const nextIndex = ref(0)

/**
 * 生成对比色（HSL 色环均匀取点）
 * 已有颜色数量 >= 7 时使用
 */
function generateContrastColor(existingCount: number): string {
  // 黄金角 137.508°，保证均匀分布
  const hue = (existingCount * 137.508) % 360
  return `hsl(${hue}, 70%, 55%)`
}

/**
 * 获取角色颜色（首次出现按顺序分配，之后固定）
 */
function getColor(name: string | undefined | null): string {
  if (!name) return RAINBOW_7[0]  // 默认红色

  // 已分配过，直接返回
  if (colorMap.value.has(name)) {
    return colorMap.value.get(name)!
  }

  // 首次分配
  let color: string
  if (nextIndex.value < RAINBOW_7.length) {
    // 优先使用彩虹七色
    color = RAINBOW_7[nextIndex.value]
  } else {
    // 超过7个角色，生成对比色
    color = generateContrastColor(nextIndex.value)
  }

  colorMap.value.set(name, color)
  nextIndex.value++
  return color
}

/**
 * 重置颜色（切换会话时调用）
 */
function resetColors() {
  colorMap.value.clear()
  nextIndex.value = 0
}

export function useCharacterColors() {
  return {
    getColor,
    resetColors,
    colorMap: readonly(colorMap)
  }
}
