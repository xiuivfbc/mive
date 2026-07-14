<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as d3 from 'd3'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'
import { useTheme } from '@/composables/useTheme'
import NodeDetailDrawer from './NodeDetailDrawer.vue'
import EdgeDetailDrawer from './EdgeDetailDrawer.vue'

const props = defineProps<{
  worldId: string
  characters: Character[]
  relations: Relation[]
  showCodes?: boolean
  readonly?: boolean
}>()

const emit = defineEmits<{
  'node-click': [id: string]
  'character-updated': [c: Character]
  'character-deleted': [id: string]
  'relation-updated': [r: Relation]
  'relation-deleted': [id: string]
}>()

const { theme, mode } = useTheme()

// .graph-canvas__wrapper 暗色模式下用淡化后的主题色（见 <style> 同名 color-mix 规则）；
// 边标签底色 / 文字描边要与画布背景一致才能"盖住"穿过的连线，因此这里同步做一次淡化
function graphCanvasBg(): string {
  const raw = getCssVar('--bg-card')
  return mode.value === 'dark' ? `color-mix(in srgb, ${raw} 20%, #202225 80%)` : raw
}

const containerRef = ref<HTMLDivElement | null>(null)
const svgRef = ref<SVGSVGElement | null>(null)

// Node drawer state
const drawerVisible = ref(false)
const selectedCharacter = ref<Character | null>(null)

// Edge drawer state
const edgeDrawerVisible = ref(false)
const selectedRelations = ref<Relation[]>([])

// Filter state
const tierFilter = ref<Set<string>>(new Set())
const searchQuery = ref('')
const debouncedSearchQuery = ref('')
const layoutMode = ref<'concentric' | 'force'>('concentric')

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, (val) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { debouncedSearchQuery.value = val }, 500)
})

const PALETTE = [
  '#f43f5e','#fb923c','#fbbf24','#a3e635',
  '#34d399','#22d3ee','#818cf8','#c084fc',
  '#f472b6','#38bdf8','#2dd4bf','#e879f9',
]

// 同色相但明度/饱和度为暗色画布重新校准（OKLCH L 落在 0.48–0.67），
// 避免直接复用亮色档位在暗色背景下显脏发土
const PALETTE_DARK = [
  '#f43f5e','#ea580c','#a68600','#65a30d',
  '#059669','#0891b2','#2563eb','#9333ea',
  '#db2777','#0284c7','#0d9488','#c026d3',
]

function hashColor(id: string): string {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  const palette = mode.value === 'dark' ? PALETTE_DARK : PALETTE
  return palette[h % palette.length]
}

function blendColor(hex1: string, hex2: string): string {
  const [r1, g1, b1] = [hex1.slice(1, 3), hex1.slice(3, 5), hex1.slice(5, 7)].map(h => parseInt(h, 16))
  const [r2, g2, b2] = [hex2.slice(1, 3), hex2.slice(3, 5), hex2.slice(5, 7)].map(h => parseInt(h, 16))
  const r = Math.round((r1 + r2) / 2), g = Math.round((g1 + g2) / 2), b = Math.round((b1 + b2) / 2)
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

function getCssVar(name: string): string {
  const el = containerRef.value || document.documentElement
  return getComputedStyle(el).getPropertyValue(name).trim()
}

const tiers = computed(() => {
  const t = new Set<string>()
  props.characters.forEach(c => { if (c.tier) t.add(c.tier) })
  return [...t].sort()
})

const visibleCharacters = computed(() =>
  props.characters.filter(c => {
    if (tierFilter.value.size > 0 && c.tier && !tierFilter.value.has(c.tier)) return false
    if (debouncedSearchQuery.value && !c.name.toLowerCase().includes(debouncedSearchQuery.value.toLowerCase())) return false
    return true
  })
)

const visibleCharIds = computed(() => new Set(visibleCharacters.value.map(c => c.id)))

const visibleRelations = computed(() =>
  props.relations.filter(r =>
    r.status === 'active' &&
    visibleCharIds.value.has(r.character_a) &&
    visibleCharIds.value.has(r.character_b)
  )
)

// 稀疏模式：可见关系线较少时，关系线默认直接可点击（不需要先选中节点/边）
const isSparseMode = computed(() => visibleRelations.value.length < 15)

function pairKey(a: string, b: string): string {
  return [a, b].sort().join('__')
}

// ── D3 internals ──────────────────────────────────────────────────────────────
let simulation: d3.Simulation<any, any> | null = null
let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null
let gRoot: d3.Selection<SVGGElement, unknown, null, undefined> | null = null
let codeBadges: d3.Selection<SVGTextElement, any, SVGGElement, unknown> | null = null

// 持久选中状态（跨 render 保持）
let selectedNodeId: string | null = null
let selectedEdgeId: string | null = null
let hasSelection = false // 只有选中节点/边时关系线才可点击

// D3 selections (persisted across renders for enter/update/exit)
let linkSel: d3.Selection<SVGPathElement, any, SVGGElement, unknown> | null = null
let edgeLabelBgSel: d3.Selection<SVGRectElement, any, SVGGElement, unknown> | null = null
let edgeLabelTextSel: d3.Selection<SVGTextElement, any, SVGGElement, unknown> | null = null
let nodeSel: d3.Selection<SVGCircleElement, any, SVGGElement, unknown> | null = null
let nodeLabelSel: d3.Selection<SVGTextElement, any, SVGGElement, unknown> | null = null
let linkGroupSel: d3.Selection<SVGGElement, unknown, SVGGElement, unknown> | null = null
let nodeGroupSel: d3.Selection<SVGGElement, unknown, SVGGElement, unknown> | null = null
let svgInitialized = false
let tickRafId = 0

function genCode(i: number): string {
  const a = 'abcdefghijklmnopqrstuvwxyz'
  return i < 26 ? a[i] : a[Math.floor((i - 26) / 26)] + a[(i - 26) % 26]
}


function getNodeRadius(tier: string): number {
  return tier === 'core' ? 14 : tier === 'extra' ? 8 : 11
}

// ── Geometry helpers ──────────────────────────────────────────────────────────
function getLinkPath(d: any): string {
  const sx = d.source.x ?? 0, sy = d.source.y ?? 0
  const tx = d.target.x ?? 0, ty = d.target.y ?? 0
  if (d.isSelfLoop) {
    const r = 28
    return `M${sx + 8},${sy - 4} A${r},${r} 0 1,1 ${sx + 8},${sy + 4}`
  }
  if (d.curvature === 0) return `M${sx},${sy} L${tx},${ty}`
  const dx = tx - sx, dy = ty - sy
  const dist = Math.sqrt(dx * dx + dy * dy) || 1
  const offsetRatio = 0.25 + (d.pairTotal || 1) * 0.05
  const base = Math.max(35, dist * offsetRatio)
  const cx = (sx + tx) / 2 + (-dy / dist) * d.curvature * base
  const cy = (sy + ty) / 2 + (dx / dist) * d.curvature * base
  return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`
}

function getLinkMid(d: any): { x: number; y: number } {
  const sx = d.source.x ?? 0, sy = d.source.y ?? 0
  const tx = d.target.x ?? 0, ty = d.target.y ?? 0
  if (d.isSelfLoop) return { x: sx + 60, y: sy }
  if (d.curvature === 0) return { x: (sx + tx) / 2, y: (sy + ty) / 2 }
  const dx = tx - sx, dy = ty - sy
  const dist = Math.sqrt(dx * dx + dy * dy) || 1
  const offsetRatio = 0.25 + (d.pairTotal || 1) * 0.05
  const base = Math.max(35, dist * offsetRatio)
  const qcx = (sx + tx) / 2 + (-dy / dist) * d.curvature * base
  const qcy = (sy + ty) / 2 + (dx / dist) * d.curvature * base
  return { x: 0.25 * sx + 0.5 * qcx + 0.25 * tx, y: 0.25 * sy + 0.5 * qcy + 0.25 * ty }
}

function updateEdgeLabels() {
  if (!edgeLabelTextSel || !edgeLabelBgSel) return
  edgeLabelTextSel.each(function(d: any) {
    const m = getLinkMid(d)
    d3.select(this).attr('x', m.x).attr('y', m.y)
  })
  edgeLabelBgSel.each(function(this: SVGRectElement, _d: any, i: number) {
    const textEl = edgeLabelTextSel!.nodes()[i]
    if (!textEl || (textEl as SVGTextElement).style.display === 'none') return
    try {
      const bb = (textEl as SVGTextElement).getBBox()
      const m = getLinkMid(_d)
      d3.select(this)
        .attr('x', m.x - bb.width / 2 - 5)
        .attr('y', m.y - bb.height / 2 - 3)
        .attr('width', bb.width + 10)
        .attr('height', bb.height + 6)
    } catch { /* ignore */ }
  })
}

// ── Event handlers (module-level to avoid re-creation) ────────────────────────
const EDGE_HOVER_WIDTH = 2.5 // 稀疏模式下 hover 时的线宽，介于默认(2)与选中态(2.5/3)之间

function handleEdgeClick(_event: MouseEvent, d: any) {
  if (!hasSelection && !isSparseMode.value) return // 稀疏模式下无需先选中，关系线也可直接点击
  hasSelection = true
  selectedNodeId = null
  selectedEdgeId = d.rawData.id
  drawerVisible.value = false
  applyEdgeSelection(d)
  if (!props.readonly) {
    const key = pairKey(d.rawData.character_a, d.rawData.character_b)
    const rels = props.relations.filter(r => r.status === 'active' && pairKey(r.character_a, r.character_b) === key)
    if (rels.length) { selectedRelations.value = rels; edgeDrawerVisible.value = true }
  }
}

function handleEdgeMouseEnter(event: MouseEvent, _d: any) {
  if (!isSparseMode.value || selectedNodeId || selectedEdgeId) return // 仅稀疏模式 + 未选中默认态生效
  d3.select(event.currentTarget as SVGPathElement).attr('stroke-width', EDGE_HOVER_WIDTH)
}

function handleEdgeMouseLeave(event: MouseEvent, _d: any) {
  if (!isSparseMode.value || selectedNodeId || selectedEdgeId) return
  d3.select(event.currentTarget as SVGPathElement).attr('stroke-width', 2)
}

let nodeDblClickTs = 0        // 节点双击时间戳；抑制 SVG dblclick
let lastNodeClickTs = 0       // 上次节点单击时间
let lastNodeClickId = ''      // 上次单击的节点 ID
let pendingFitTimer: ReturnType<typeof setTimeout> | null = null
const DBLCLICK_MS = 300       // 双击判定阈值

function handleNodeClick(_event: MouseEvent, d: any) {
  const now = Date.now()
  const isDblClick = (now - lastNodeClickTs < DBLCLICK_MS) && (lastNodeClickId === d.id)
  lastNodeClickTs = now
  lastNodeClickId = d.id

  const wasAlreadySelected = selectedNodeId === d.id
  selectedNodeId = d.id
  selectedEdgeId = null
  hasSelection = true
  applyNodeSelection(d.id, false)   // 暂不 fit

  if (!props.readonly) {
    if (isDblClick) {
      // 双击节点：fit 视口 + 打开详情抽屉
      if (pendingFitTimer) { clearTimeout(pendingFitTimer); pendingFitTimer = null }
      nodeDblClickTs = now
      applyNodeSelection(d.id, true)  // 立即 fit
      const char = props.characters.find(c => c.id === d.id)
      if (char) { selectedCharacter.value = char; drawerVisible.value = true }
    } else if (wasAlreadySelected) {
      // 再次点击已选中节点：打开详情抽屉
      if (pendingFitTimer) { clearTimeout(pendingFitTimer); pendingFitTimer = null }
      const char = props.characters.find(c => c.id === d.id)
      if (char) { selectedCharacter.value = char; drawerVisible.value = true }
    } else {
      // 首次单击新节点：关闭已打开的抽屉，延迟 fit（等双击窗口过去）
      drawerVisible.value = false
      edgeDrawerVisible.value = false
      if (pendingFitTimer) clearTimeout(pendingFitTimer)
      pendingFitTimer = setTimeout(() => {
        pendingFitTimer = null
        if (selectedNodeId === d.id) applyNodeSelection(d.id, true)
      }, DBLCLICK_MS)
    }
    emit('node-click', d.id)
  }
}

function handleNodeMouseEnter(_event: MouseEvent, d: any) {
  if (selectedNodeId || selectedEdgeId) return
  nodeSel!.filter((n: any) => n.id === d.id).attr('stroke', hashColor(d.id)).attr('stroke-width', 3)
}

function handleNodeMouseLeave(_event: MouseEvent, d: any) {
  if (selectedNodeId) { applyNodeSelection(selectedNodeId); return }
  if (selectedEdgeId) return
  nodeSel!.filter((n: any) => n.id === d.id).attr('stroke', '#fff').attr('stroke-width', 2)
}

function handleSvgClick(event: MouseEvent) {
  if ((event.target as SVGElement).tagName === 'svg') {
    selectedNodeId = null; selectedEdgeId = null
    hasSelection = false
    drawerVisible.value = false
    edgeDrawerVisible.value = false
    resetHighlight()
    // 点击空白区域显示所有关系线
    linkSel?.attr('opacity', 1)
  }
}

/** 空白处双击：显示所有关系线 + 全局鸟瞰视角 */
function handleSvgDblClick(event: MouseEvent) {
  if ((event.target as SVGElement).tagName !== 'svg') return
  // 节点双击刚触发过，跳过（防止 dblclick 事件冒泡到 SVG 干扰）
  if (Date.now() - nodeDblClickTs < 300) return
  // 清除选中状态（同单击逻辑）
  selectedNodeId = null; selectedEdgeId = null
  hasSelection = false
  drawerVisible.value = false
  edgeDrawerVisible.value = false
  resetHighlight()
  linkSel?.attr('opacity', 1)
  // 全局鸟瞰
  fitAllNodes()
}

// ── Highlight helpers ─────────────────────────────────────────────────────────
function showEdgeLabels(_filterFn: (d: any) => boolean) {
  if (!edgeLabelTextSel || !edgeLabelBgSel) return
  // 关系线不显示名称标签，保持隐藏
  edgeLabelTextSel.style('display', 'none')
  edgeLabelBgSel.style('display', 'none')
}

function resetHighlight() {
  if (!nodeSel || !linkSel || !edgeLabelTextSel || !edgeLabelBgSel) return
  nodeSel.attr('stroke', '#fff').attr('stroke-width', 2).attr('opacity', 1)
  linkSel.attr('opacity', 0).attr('stroke', '#aaa').attr('stroke-width', 2)
    .style('pointer-events', isSparseMode.value ? 'auto' : 'none')
  edgeLabelTextSel.style('display', 'none')
  edgeLabelBgSel.style('display', 'none')
}

function applyNodeSelection(id: string, doFit = false) {
  if (!nodeSel || !linkSel) return
  // 找出与选中节点有关系的节点
  const connected = new Set<string>()
  linkSel.each((d: any) => {
    if (d.source.id === id) connected.add(d.target.id)
    if (d.target.id === id) connected.add(d.source.id)
  })
  nodeSel.attr('opacity', (d: any) => d.id === id || connected.has(d.id) ? 1 : 0.1)
  nodeSel.filter((d: any) => d.id === id).attr('stroke', hashColor(id)).attr('stroke-width', 3.5)
  nodeSel.filter((d: any) => d.id !== id && connected.has(d.id))
    .attr('stroke', hashColor(id)).attr('stroke-width', 2)
  nodeSel.filter((d: any) => d.id !== id && !connected.has(d.id))
    .attr('stroke', '#fff').attr('stroke-width', 2)
  linkSel.attr('opacity', 0).style('pointer-events', 'none')
  linkSel.filter((e: any) => e.source.id === id || e.target.id === id)
    .attr('stroke', hashColor(id)).attr('stroke-width', 2.5).attr('opacity', 1)
    .style('pointer-events', 'auto')
  showEdgeLabels((d: any) => d.source.id === id || d.target.id === id)
  if (doFit) fitToNodes(new Set([id, ...connected]))
}

function applyEdgeSelection(edgeData: any) {
  if (!nodeSel || !linkSel) return
  const idA = edgeData.source.id
  const idB = edgeData.target.id
  // 关联节点：分别收集 A 和 B 各自的连接
  const connA = new Set<string>()
  const connB = new Set<string>()
  linkSel.each((d: any) => {
    if (d.source.id === idA) connA.add(d.target.id)
    if (d.target.id === idA) connA.add(d.source.id)
    if (d.source.id === idB) connB.add(d.target.id)
    if (d.target.id === idB) connB.add(d.source.id)
  })
  const allVisible = new Set([idA, idB, ...connA, ...connB])
  const abColor = blendColor(hashColor(idA), hashColor(idB))
  // 节点高亮
  nodeSel.attr('opacity', (d: any) => allVisible.has(d.id) ? 1 : 0.1)
  nodeSel.filter((d: any) => d.id === idA || d.id === idB)
    .attr('stroke', abColor).attr('stroke-width', 3)
  nodeSel.filter((d: any) => d.id !== idA && d.id !== idB && connA.has(d.id))
    .attr('stroke', hashColor(idA)).attr('stroke-width', 2)
  nodeSel.filter((d: any) => d.id !== idA && d.id !== idB && connB.has(d.id))
    .attr('stroke', hashColor(idB)).attr('stroke-width', 2)
  nodeSel.filter((d: any) => !allVisible.has(d.id))
    .attr('stroke', '#fff').attr('stroke-width', 2)
  // 关系线：三色分类
  linkSel.attr('opacity', 0).style('pointer-events', 'none')
  // A-B 自身：混合色粗线
  linkSel.filter((e: any) =>
    (e.source.id === idA && e.target.id === idB) || (e.source.id === idB && e.target.id === idA)
  ).attr('stroke', abColor).attr('stroke-width', 3).attr('opacity', 1).style('pointer-events', 'auto')
  // A 的关系线
  linkSel.filter((e: any) => {
    const isAB = (e.source.id === idA && e.target.id === idB) || (e.source.id === idB && e.target.id === idA)
    return !isAB && (e.source.id === idA || e.target.id === idA)
  }).attr('stroke', hashColor(idA)).attr('stroke-width', 2.5).attr('opacity', 1).style('pointer-events', 'auto')
  // B 的关系线
  linkSel.filter((e: any) => {
    const isAB = (e.source.id === idA && e.target.id === idB) || (e.source.id === idB && e.target.id === idA)
    return !isAB && (e.source.id === idB || e.target.id === idB)
  }).attr('stroke', hashColor(idB)).attr('stroke-width', 2.5).attr('opacity', 1).style('pointer-events', 'auto')
  // 标签
  const isVisibleEdge = (e: any) =>
    (e.source.id === idA || e.target.id === idA || e.source.id === idB || e.target.id === idB)
  showEdgeLabels(isVisibleEdge)
  fitToNodes(allVisible)
}

/** 平移+缩放视口，使目标节点群落入可视区 */
function fitToNodes(ids: Set<string>) {
  if (!svgRef.value || !zoomBehavior || !containerRef.value || !nodeSel) return
  const nodes: any[] = []
  nodeSel.each((d: any) => { if (ids.has(d.id)) nodes.push(d) })
  if (nodes.length === 0) return

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    const r = getNodeRadius(n.tier)
    if (n.x - r < minX) minX = n.x - r
    if (n.y - r < minY) minY = n.y - r
    if (n.x + r > maxX) maxX = n.x + r
    if (n.y + r > maxY) maxY = n.y + r
  }

  const pad = 80 // 节点到边缘的留白
  const cw = containerRef.value.clientWidth
  const ch = containerRef.value.clientHeight
  const bw = maxX - minX
  const bh = maxY - minY

  // 缩放：让包围盒 + padding 填满视口，但不超过最大倍率，不低于 0.3
  const k = Math.min(cw / (bw + pad * 2), ch / (bh + pad * 2), 2)
  const kClamped = Math.max(k, 0.3)
  // 居中
  const tx = cw / 2 - (minX + maxX) / 2 * kClamped
  const ty = ch / 2 - (minY + maxY) / 2 * kClamped

  d3.select(svgRef.value)
    .transition().duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(kClamped))
}

/** 全局鸟瞰：fit 视口到所有节点 */
function fitAllNodes() {
  if (!nodeSel) return
  const allIds = new Set<string>()
  nodeSel.each((d: any) => allIds.add(d.id))
  if (allIds.size === 0) return
  fitToNodes(allIds)
}

// ── SVG one-time initialization ───────────────────────────────────────────────
function initSvg() {
  if (!containerRef.value || !svgRef.value || svgInitialized) return

  const container = containerRef.value
  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(svgRef.value)
    .attr('width', width)
    .attr('height', height)

  // Defs: arrowhead
  const defs = svg.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -4 8 8')
    .attr('refX', 18)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-4L8,0L0,4')
    .attr('fill', '#aaa')

  const g = svg.append('g')
  gRoot = g

  // Zoom
  let zoomStartTransform: any = null
  let hadSelectionAtZoomStart = false
  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.1, 4])
    .on('zoom', event => g.attr('transform', event.transform))
    .on('start', (event) => {
      if (event.sourceEvent) {
        zoomStartTransform = event.transform.toString()
        hadSelectionAtZoomStart = !!selectedNodeId || !!selectedEdgeId
        // 拖动开始：隐藏所有关系线
        linkSel?.attr('opacity', 0)
      }
    })
    .on('end', (event) => {
      updateEdgeLabels()
      // 仅当真正发生了缩放/平移时清除选中态（简单点击不触发）
      if (event.sourceEvent && zoomStartTransform && event.transform.toString() !== zoomStartTransform) {
        selectedNodeId = null; selectedEdgeId = null
        hasSelection = false
        drawerVisible.value = false
        edgeDrawerVisible.value = false
        resetHighlight()
      } else if (!selectedNodeId && !selectedEdgeId) {
        // 无选中态时拖动结束：恢复显示所有关系线
        linkSel?.attr('opacity', 1)
      }
      zoomStartTransform = null
      hadSelectionAtZoomStart = false
    })

  zoomBehavior = zoom
  svg.call(zoom)
  svg.on('dblclick.zoom', null)
  svg.on('dblclick.fit', handleSvgDblClick)

  // Groups
  linkGroupSel = g.append('g').attr('class', 'links') as any
  nodeGroupSel = g.append('g').attr('class', 'nodes') as any

  svgInitialized = true
}

function render() {
  if (!containerRef.value || !svgRef.value) return

  initSvg()

  const cssVars = {
    bgCard: graphCanvasBg(),
    textPrimary: getCssVar('--text-primary'),
    textSecondary: getCssVar('--text-secondary'),
  }

  const container = containerRef.value
  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(svgRef.value)
    .attr('width', width)
    .attr('height', height)

  const chars = visibleCharacters.value
  const rels = visibleRelations.value

  if (chars.length === 0) {
    // Clear stale SVG elements from previous render
    linkGroupSel?.selectAll('path').remove()
    linkGroupSel?.selectAll('rect').remove()
    linkGroupSel?.selectAll('text').remove()
    nodeGroupSel?.selectAll('circle').remove()
    nodeGroupSel?.selectAll('text').remove()
    linkSel = null; edgeLabelBgSel = null; edgeLabelTextSel = null
    nodeSel = null; nodeLabelSel = null; codeBadges = null
    simulation?.stop()
    simulation = null
    return
  }

  // Build node/edge data
  const nodeMap = new Map(chars.map(c => [c.id, c]))

  const nodes: any[] = chars.map(c => ({
    id: c.id,
    name: c.name,
    entityType: c.entity_type || 'character',
    tier: c.tier || 'supporting',
    rawData: c,
  }))

  // Count edges per pair for curvature
  const pairCount: Record<string, number> = {}
  const pairIndex: Record<string, number> = {}
  const selfLoopMap: Record<string, any[]> = {}
  const processedSelfLoops = new Set<string>()

  const tempEdges = rels.filter(r => nodeMap.has(r.character_a) && nodeMap.has(r.character_b))

  tempEdges.forEach(r => {
    if (r.character_a === r.character_b) {
      if (!selfLoopMap[r.character_a]) selfLoopMap[r.character_a] = []
      selfLoopMap[r.character_a].push(r)
    } else {
      const key = pairKey(r.character_a, r.character_b)
      pairCount[key] = (pairCount[key] || 0) + 1
    }
  })

  const edges: any[] = []

  tempEdges.forEach(r => {
    if (r.character_a === r.character_b) {
      if (processedSelfLoops.has(r.character_a)) return
      processedSelfLoops.add(r.character_a)
      const loops = selfLoopMap[r.character_a]
      edges.push({
        source: r.character_a,
        target: r.character_b,
        label: `自关联 (${loops.length})`,
        isSelfLoop: true,
        curvature: 0,
        pairTotal: 1,
        rawData: r,
      })
      return
    }
    const key = pairKey(r.character_a, r.character_b)
    const total = pairCount[key]
    const idx = pairIndex[key] || 0
    pairIndex[key] = idx + 1
    const isReversed = r.character_a > r.character_b
    let curvature = isReversed ? -0.25 : 0.25
    if (total > 1) {
      const range = Math.min(1.2, 0.6 + total * 0.15)
      curvature = ((idx / (total - 1)) - 0.5) * range * 2
      if (isReversed) curvature = -curvature
    }
    edges.push({
      source: r.character_a,
      target: r.character_b,
      label: r.type || '',
      isSelfLoop: false,
      curvature,
      pairTotal: total,
      rawData: r,
    })
  })

  // Large graph optimization
  const isLargeGraph = nodes.length > 100

  // ── Edges (enter/update/exit) ──
  linkSel = linkGroupSel!.selectAll<SVGPathElement, any>('path')
    .data(edges, (d: any) => d.rawData.id)
    .join(
      enter => enter.append('path')
        .attr('fill', 'none')
        .attr('stroke', '#aaa')
        .attr('stroke-width', 2)
        .attr('opacity', 0)
        .style('pointer-events', () => isSparseMode.value ? 'auto' : 'none')
        .style('cursor', 'pointer')
        .on('click', handleEdgeClick)
        .on('mouseenter', handleEdgeMouseEnter)
        .on('mouseleave', handleEdgeMouseLeave),
      update => update,
      exit => exit.remove()
    )

  // 未选中默认态下，pointer-events 依据稀疏模式动态刷新（选中态由 applyNodeSelection/applyEdgeSelection 接管，不受此处影响）
  if (!selectedNodeId && !selectedEdgeId) {
    linkSel.style('pointer-events', isSparseMode.value ? 'auto' : 'none')
  }

  // ── Edge label backgrounds ──
  if (isLargeGraph) {
    edgeLabelBgSel = linkGroupSel!.selectAll<SVGRectElement, any>('rect').data([]) as any
    edgeLabelBgSel!.join('rect') // effectively removes all
  } else {
    edgeLabelBgSel = linkGroupSel!.selectAll<SVGRectElement, any>('rect')
      .data(edges, (d: any) => d.rawData.id)
      .join(
        enter => enter.append('rect')
          .style('fill', `color-mix(in srgb, ${cssVars.bgCard} 88%, transparent)`)
          .attr('rx', 4)
          .style('display', 'none')
          .style('pointer-events', 'none'),
        update => update
          .style('fill', `color-mix(in srgb, ${cssVars.bgCard} 88%, transparent)`),
        exit => exit.remove()
      )
  }

  // ── Edge label text ──
  if (isLargeGraph) {
    edgeLabelTextSel = linkGroupSel!.selectAll<SVGTextElement, any>('text').data([]) as any
    edgeLabelTextSel!.join('text')
  } else {
    edgeLabelTextSel = linkGroupSel!.selectAll<SVGTextElement, any>('text')
      .data(edges, (d: any) => d.rawData.id)
      .join(
        enter => enter.append('text')
          .attr('font-size', '10px')
          .attr('fill', cssVars.textSecondary)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('font-family', '"Noto Sans SC", system-ui, sans-serif')
          .style('display', 'none')
          .style('pointer-events', 'none'),
        update => update.attr('fill', cssVars.textSecondary),
        exit => exit.remove()
      )
      .text((d: any) => d.label || '')
  }

  // ── Nodes (enter/update/exit) ──
  const dragHandler = d3.drag<SVGCircleElement, any>()
    .on('start', (event, d) => {
      d._dragStartX = event.x; d._dragStartY = event.y; d._dragging = false
      d.fx = d.x; d.fy = d.y
    })
    .on('drag', (event, d) => {
      const dist = Math.hypot(event.x - d._dragStartX, event.y - d._dragStartY)
      if (!d._dragging && dist > 4) { d._dragging = true; simulation?.alphaTarget(0.3).restart() }
      if (d._dragging) { d.fx = event.x; d.fy = event.y }
    })
    .on('end', (_event, d) => {
      if (d._dragging) { simulation?.alphaTarget(0); updateEdgeLabels() }
      d.fx = null; d.fy = null; d._dragging = false
    })

  nodeSel = nodeGroupSel!.selectAll<SVGCircleElement, any>('circle')
    .data(nodes, (d: any) => d.id)
    .join(
      enter => enter.append('circle')
        .attr('r', (d: any) => getNodeRadius(d.tier))
        .attr('fill', (d: any) => hashColor(d.id))
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .call(dragHandler)
        .on('click', handleNodeClick)
        .on('mouseenter', handleNodeMouseEnter)
        .on('mouseleave', handleNodeMouseLeave),
      update => update
        .attr('r', (d: any) => getNodeRadius(d.tier))
        .attr('fill', (d: any) => hashColor(d.id)),
      exit => exit.remove()
    )

  // ── Node labels (enter/update/exit) ──
  nodeLabelSel = nodeGroupSel!.selectAll<SVGTextElement, any>('text:not(.code-badge)')
    .data(nodes, (d: any) => d.id)
    .join(
      enter => enter.append('text')
        .attr('font-size', '11px')
        .attr('fill', cssVars.textPrimary)
        .attr('font-weight', '500')
        .attr('font-family', '"Noto Sans SC", system-ui, sans-serif')
        .style('paint-order', 'stroke')
        .style('stroke', cssVars.bgCard)
        .style('stroke-width', '3px')
        .style('pointer-events', 'none'),
      update => update
        .attr('fill', cssVars.textPrimary)
        .style('stroke', cssVars.bgCard),
      exit => exit.remove()
    )
    .text((d: any) => d.name.length > 6 ? d.name.slice(0, 6) + '…' : d.name)
    .attr('dx', (d: any) => getNodeRadius(d.tier) + 4)
    .attr('dy', 4)

  // ── Code badges (enter/update/exit) ──
  const charCodeMap = new Map<string, string>(
    props.characters.map((c, i) => [c.id, genCode(i)])
  )
  codeBadges = nodeGroupSel!.selectAll<SVGTextElement, any>('.code-badge')
    .data(nodes, (d: any) => d.id)
    .join(
      enter => enter.append('text')
        .attr('class', 'code-badge')
        .attr('font-size', '11px')
        .attr('font-family', '"Courier New", "Consolas", monospace')
        .attr('font-weight', '800')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'auto')
        .attr('fill', '#fde047')
        .style('paint-order', 'stroke')
        .style('stroke', 'rgba(0,0,0,0.95)')
        .style('stroke-width', '3px')
        .style('pointer-events', 'none')
        .style('display', props.showCodes ? '' : 'none'),
      update => update.style('display', props.showCodes ? '' : 'none'),
      exit => exit.remove()
    )
    .text((d: any) => charCodeMap.get(d.id) ?? '')
    .attr('x', (d: any) => d.x)
    .attr('y', (d: any) => (d.y ?? 0) - getNodeRadius(d.tier) - 3)

  // Restore previous selection state
  if (selectedNodeId && nodes.find((n: any) => n.id === selectedNodeId)) {
    applyNodeSelection(selectedNodeId)
  } else if (selectedEdgeId) {
    const edgeDatum = linkSel?.data().find((d: any) => d.rawData.id === selectedEdgeId)
    if (edgeDatum) {
      applyEdgeSelection(edgeDatum)
    } else {
      selectedEdgeId = null
    }
  }

  // Click on blank to deselect (only bind once)
  svg.on('click', handleSvgClick)

  // ── Simulation ──
  const cx = width / 2, cy = height / 2

  if (layoutMode.value === 'concentric') {
    const minDim = Math.min(width, height)
    const coreCount = nodes.filter((n: any) => n.tier === 'core').length
    const suppCount = nodes.filter((n: any) => n.tier === 'supporting').length
    const extraCount = nodes.filter((n: any) => n.tier === 'extra').length
    const rInner = coreCount <= 1 ? 0 : Math.max(60, minDim * 0.13)
    const rMid = Math.max(rInner + 100, minDim * 0.32 + suppCount * 3)
    const rOuter = Math.max(rMid + 100, minDim * 0.46 + extraCount * 3)
    const tierRadius: Record<string, number> = { core: rInner, supporting: rMid, extra: rOuter }
    // 预置节点到对应层级半径上，避免从中心向外爆炸产生"跳动感"
    nodes.forEach((n: any) => {
      const r = tierRadius[n.tier] ?? rOuter
      const angle = Math.random() * 2 * Math.PI
      n.x = cx + r * Math.cos(angle)
      n.y = cy + r * Math.sin(angle)
    })

    if (simulation) {
      simulation.stop()
      simulation.nodes(nodes)
      ;(simulation.force('link') as d3.ForceLink<any, any>).links(edges).id((d: any) => d.id).distance(60).strength(0.08)
      simulation.force('charge', d3.forceManyBody().strength(-400).distanceMax(500))
      simulation.force('radial', d3.forceRadial((d: any) => tierRadius[d.tier] ?? rOuter, cx, cy).strength(0.75))
      simulation.force('collide', d3.forceCollide((d: any) => getNodeRadius(d.tier) + 20).strength(1).iterations(4))
      // Remove forces from force layout mode if switching from force → concentric
      simulation.force('center', null)
      simulation.force('x', null)
      simulation.force('y', null)
      simulation.alphaDecay(0.010)
      simulation.velocityDecay(0.35)
      simulation.alpha(0.1).restart()
    } else {
      simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(60).strength(0.08))
        .force('charge', d3.forceManyBody().strength(-400).distanceMax(500))
        .force('radial', d3.forceRadial((d: any) => tierRadius[d.tier] ?? rOuter, cx, cy).strength(0.75))
        .force('collide', d3.forceCollide((d: any) => getNodeRadius(d.tier) + 20).strength(1).iterations(4))
        .alphaDecay(0.010)
        .velocityDecay(0.35)
      simulation.alpha(0.1)
      // 同步推演使节点在首帧前稳定，消除初始跳变
      simulation.stop()
      for (let i = 0; i < 200; i++) simulation.tick()
      nodeSel?.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)
      nodeLabelSel?.attr('x', (d: any) => d.x).attr('y', (d: any) => d.y)
      codeBadges?.attr('x', (d: any) => d.x).attr('y', (d: any) => (d.y ?? 0) - getNodeRadius(d.tier) - 3)
      linkSel?.attr('d', (d: any) => getLinkPath(d))
      simulation.alpha(0.02).restart()
    }
  } else {
    const nodeCount = nodes.length
    const repulsion = Math.max(-1200, -400 - nodeCount * 30)
    const linkDist = Math.min(280, 180 + nodeCount * 4)

    if (simulation) {
      simulation.stop()
      simulation.nodes(nodes)
      ;(simulation.force('link') as d3.ForceLink<any, any>).links(edges).id((d: any) => d.id).distance(linkDist).strength(0.4)
      simulation.force('charge', d3.forceManyBody().strength(repulsion).distanceMax(600))
      simulation.force('center', d3.forceCenter(cx, cy).strength(0.08))
      simulation.force('collide', d3.forceCollide((d: any) => getNodeRadius(d.tier) * 4 + 20).strength(1).iterations(3))
      simulation.force('x', d3.forceX(cx).strength(0.02))
      simulation.force('y', d3.forceY(cy).strength(0.02))
      // Remove force from concentric layout mode if switching from concentric → force
      simulation.force('radial', null)
      simulation.alphaDecay(0.015)
      simulation.velocityDecay(0.4)
      simulation.alpha(0.1).restart()
    } else {
      simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(linkDist).strength(0.4))
        .force('charge', d3.forceManyBody().strength(repulsion).distanceMax(600))
        .force('center', d3.forceCenter(cx, cy).strength(0.08))
        .force('collide', d3.forceCollide((d: any) => getNodeRadius(d.tier) * 4 + 20).strength(1).iterations(3))
        .force('x', d3.forceX(cx).strength(0.02))
        .force('y', d3.forceY(cy).strength(0.02))
        .alphaDecay(0.015)
        .velocityDecay(0.4)
        .alpha(0.1)
      // 同步推演使节点在首帧前稳定，消除初始跳变
      simulation.stop()
      for (let i = 0; i < 200; i++) simulation.tick()
      nodeSel?.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)
      nodeLabelSel?.attr('x', (d: any) => d.x).attr('y', (d: any) => d.y)
      codeBadges?.attr('x', (d: any) => d.x).attr('y', (d: any) => (d.y ?? 0) - getNodeRadius(d.tier) - 3)
      linkSel?.attr('d', (d: any) => getLinkPath(d))
      simulation.alpha(0.02).restart()
    }
  }

  if (tickRafId) { cancelAnimationFrame(tickRafId); tickRafId = 0 }
  simulation!.on('tick', () => {
    if (tickRafId) return
    tickRafId = requestAnimationFrame(() => {
      tickRafId = 0
      linkSel?.attr('d', (d: any) => getLinkPath(d))
      nodeSel?.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)
      nodeLabelSel?.attr('x', (d: any) => d.x).attr('y', (d: any) => d.y)
      codeBadges?.attr('x', (d: any) => d.x).attr('y', (d: any) => (d.y ?? 0) - getNodeRadius(d.tier) - 3)
    })
  })

  simulation!.on('end', () => { updateEdgeLabels() })
}

// ── Toolbar actions ───────────────────────────────────────────────────────────
function zoomIn() {
  if (!svgRef.value || !zoomBehavior) return
  d3.select(svgRef.value).transition().duration(250).call(zoomBehavior.scaleBy, 1.3)
}
function zoomOut() {
  if (!svgRef.value || !zoomBehavior) return
  d3.select(svgRef.value).transition().duration(250).call(zoomBehavior.scaleBy, 1 / 1.3)
}
function fit() {
  fitAllNodes()
}
function runLayout(name: string) {
  if (!simulation) return
  if (name === 'circle') {
    const n = simulation.nodes().length
    simulation.nodes().forEach((d: any, i: number) => {
      const angle = (2 * Math.PI * i) / n
      const r = Math.min(containerRef.value!.clientWidth, containerRef.value!.clientHeight) * 0.35
      d.fx = containerRef.value!.clientWidth / 2 + r * Math.cos(angle)
      d.fy = containerRef.value!.clientHeight / 2 + r * Math.sin(angle)
    })
    simulation.alpha(0.3).restart()
    setTimeout(() => { simulation?.nodes().forEach((d: any) => { d.fx = null; d.fy = null }) }, 800)
  } else if (name === 'grid') {
    const nodes = simulation.nodes()
    const cols = Math.ceil(Math.sqrt(nodes.length))
    const w = containerRef.value!.clientWidth, h = containerRef.value!.clientHeight
    nodes.forEach((d: any, i: number) => {
      d.fx = (w / (cols + 1)) * ((i % cols) + 1)
      d.fy = (h / (Math.ceil(nodes.length / cols) + 1)) * (Math.floor(i / cols) + 1)
    })
    simulation.alpha(0.3).restart()
    setTimeout(() => { simulation?.nodes().forEach((d: any) => { d.fx = null; d.fy = null }) }, 800)
  } else {
    simulation.nodes().forEach((d: any) => { d.fx = null; d.fy = null })
    simulation.alpha(0.5).restart()
  }
}

// ── Filter toggles ────────────────────────────────────────────────────────────
function toggleTier(tier: string) {
  const s = new Set(tierFilter.value)
  s.has(tier) ? s.delete(tier) : s.add(tier)
  tierFilter.value = s
}

// ── Theme-only color refresh (no simulation rebuild) ─────────────────────────
function updateThemeColors() {
  const cssVars = {
    bgCard: graphCanvasBg(),
    textPrimary: getCssVar('--text-primary'),
    textSecondary: getCssVar('--text-secondary'),
  }
  edgeLabelBgSel?.style('fill', `color-mix(in srgb, ${cssVars.bgCard} 88%, transparent)`)
  edgeLabelTextSel?.attr('fill', cssVars.textSecondary)
  nodeLabelSel?.attr('fill', cssVars.textPrimary).style('stroke', cssVars.bgCard)
  nodeSel?.attr('fill', (d: any) => hashColor(d.id))
}

// ── Watchers ──────────────────────────────────────────────────────────────────
let renderDebounceTimer: ReturnType<typeof setTimeout> | null = null
watch([visibleCharacters, visibleRelations, layoutMode], () => {
  if (renderDebounceTimer) clearTimeout(renderDebounceTimer)
  renderDebounceTimer = setTimeout(() => { nextTick(render) }, 16)
})
watch([theme, mode], () => { updateThemeColors() })
watch(() => props.showCodes, (v) => {
  codeBadges?.style('display', v ? '' : 'none')
})

let resizeTimer: ReturnType<typeof setTimeout> | null = null
let resizeObserver: ResizeObserver | null = null

const handleResize = () => {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => { nextTick(render) }, 200)
}

onMounted(() => {
  nextTick(render)
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => handleResize())
    resizeObserver.observe(containerRef.value)
  }
})
onUnmounted(() => {
  simulation?.stop()
  simulation = null
  gRoot = null
  zoomBehavior = null
  svgInitialized = false
  if (tickRafId) { cancelAnimationFrame(tickRafId); tickRafId = 0 }
  linkSel = null; edgeLabelBgSel = null; edgeLabelTextSel = null
  nodeSel = null; nodeLabelSel = null; codeBadges = null
  linkGroupSel = null; nodeGroupSel = null
  resizeObserver?.disconnect()
  if (resizeTimer) clearTimeout(resizeTimer)
  if (searchTimer) clearTimeout(searchTimer)
  if (renderDebounceTimer) clearTimeout(renderDebounceTimer)
})

function clearSelectionIfMatches(id: string) {
  if (selectedNodeId === id) {
    selectedNodeId = null
    drawerVisible.value = false
    selectedCharacter.value = null
  }
  if (selectedEdgeId === id) {
    selectedEdgeId = null
    edgeDrawerVisible.value = false
    selectedRelations.value = []
  }
  if (!selectedNodeId && !selectedEdgeId) {
    hasSelection = false
    resetHighlight()
    linkSel?.attr('opacity', 1)
  }
}

function handleDrawerRelationUpdated(r: Relation) {
  selectedRelations.value = selectedRelations.value.map(x => x.id === r.id ? r : x)
  emit('relation-updated', r)
}

function handleDrawerRelationDeleted(id: string) {
  selectedRelations.value = selectedRelations.value.filter(x => x.id !== id)
  if (selectedRelations.value.length === 0) {
    edgeDrawerVisible.value = false
    selectedEdgeId = null
  }
  emit('relation-deleted', id)
}

defineExpose({ clearSelectionIfMatches })
</script>

<template>
  <div ref="containerRef" class="graph-canvas__wrapper">
    <svg ref="svgRef" class="graph-canvas" />

    <!-- 图例：左下角 -->
    <div class="graph-canvas__legend">
      <div class="legend-section">
        <button
          v-for="tier in ['core','supporting','extra']" :key="tier"
          class="legend-chip"
          :class="{ active: tierFilter.size === 0 || tierFilter.has(tier) }"
          @click="toggleTier(tier)"
        >
          <span class="legend-node" :style="{ width: tier==='core'?'14px':tier==='supporting'?'10px':'7px', height: tier==='core'?'14px':tier==='supporting'?'10px':'7px' }" />
          {{ tier === 'core' ? $t('graph.tierCore') : tier === 'supporting' ? $t('graph.tierSupporting') : $t('graph.tierExtra') }}
        </button>
      </div>
    </div>

    <!-- 右下角：布局切换 + 搜索 -->
    <div class="graph-canvas__search">
      <div class="layout-toggle">
        <button
          class="layout-btn"
          :class="{ active: layoutMode === 'concentric' }"
          @click="layoutMode = 'concentric'"
        >{{ $t('graph.concentric') }}</button>
        <button
          class="layout-btn"
          :class="{ active: layoutMode === 'force' }"
          @click="layoutMode = 'force'"
        >{{ $t('graph.force') }}</button>
      </div>
      <input v-model="searchQuery" class="legend-search" :placeholder="$t('graph.searchPlaceholder')" />
    </div>

    <NodeDetailDrawer
      v-model:visible="drawerVisible"
      :world-id="worldId"
      :character="selectedCharacter"
      :characters="characters"
      :relations="relations"
      @character-updated="(c) => { selectedCharacter = c; emit('character-updated', c) }"
      @character-deleted="(id) => { selectedNodeId = null; emit('character-deleted', id) }"
    />
    <EdgeDetailDrawer
      v-model:visible="edgeDrawerVisible"
      :world-id="worldId"
      :relations="selectedRelations"
      :characters="characters"
      @relation-updated="handleDrawerRelationUpdated"
      @relation-deleted="handleDrawerRelationDeleted"
    />
  </div>
</template>

<style scoped>
.graph-canvas__wrapper {
  position: relative;
  width: 100%;
  min-height: 500px;
  height: calc(100vh - 280px);
  max-height: 720px;
  border: none;
  border-radius: var(--radius);
  overflow: hidden;
  color-scheme: light;
  background-color: var(--bg-card, #fff);
  background-image: radial-gradient(var(--border-subtle) 1px, transparent 1px);
  background-size: 22px 22px;
}

.graph-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.graph-canvas__legend {
  position: absolute;
  bottom: 16px;
  left: 16px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  backdrop-filter: blur(8px);
  font-size: 12px;
  max-width: 320px;
}

.graph-canvas__search {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-section {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.legend-label {
  color: var(--text-muted);
  font-size: 11px;
  flex-shrink: 0;
  margin-right: 2px;
}

.legend-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.legend-chip.active {
  border-color: var(--chip-color, var(--border-subtle));
  background: color-mix(in srgb, var(--chip-color, var(--accent)) 10%, transparent);
}

.legend-chip:not(.active) { opacity: 0.35; }

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--chip-color, #888);
  flex-shrink: 0;
}

.legend-node {
  border-radius: 50%;
  background: var(--text-secondary);
  flex-shrink: 0;
  opacity: 0.7;
}

.legend-search {
  width: 130px;
  padding: 4px 10px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 11px;
  outline: none;
  backdrop-filter: blur(8px);
}

.legend-search:focus { border-color: var(--accent); }

.layout-toggle {
  display: flex;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  overflow: hidden;
  backdrop-filter: blur(8px);
}

.layout-btn {
  padding: 4px 10px;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: 11px;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}

.layout-btn + .layout-btn {
  border-left: 1px solid rgba(0,0,0,0.06);
}

.layout-btn.active {
  background: var(--accent);
  color: var(--bg-body);
}

.legend-btn {
  padding: 4px 10px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  backdrop-filter: blur(8px);
}

.legend-btn.active {
  background: var(--accent);
  color: var(--bg-body);
  border-color: var(--accent);
}

[data-theme="breeze"][data-mode="light"] .graph-canvas__wrapper {
  background-color: #f8f9fc;
  background-image: radial-gradient(#d0d5e8 1px, transparent 1px);
}

[data-theme="ink"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="breeze"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="sakura"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="ember"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="sunflower"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="ocean"][data-mode="dark"] .graph-canvas__wrapper,
[data-theme="indigo"][data-mode="dark"] .graph-canvas__wrapper {
  background-color: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
}

</style>
