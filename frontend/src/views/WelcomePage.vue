<template>
  <div class="welcome" :class="{ leaving: isLeaving }">
    <!-- Danmaku quotes background — commented out, see WELCOME_HERO_PROTOTYPE_NOTES.md
    <div class="danmaku-layer" v-if="displayDanmaku.length > 0">
      <div
        v-for="(d, i) in displayDanmaku"
        :key="d.id + '-' + i"
        class="danmaku-item"
        :style="{
          '--top': d.top,
          '--duration': d.speed + 's',
          '--delay': d.delay + 's',
          '--color': d.color,
          '--opacity': d.opacity,
          '--font-size': d.fontSize + 'rem',
        }"
      >
        <span class="danmaku-text">{{ d.content }}</span>
      </div>
    </div>
    -->

    <!-- PROTOTYPE — hero visual "story", see NOTES.md. -->
    <!-- .hero-glow removed 2026-07-03: the graph/tags' own canvas glow is the only
         light source now, no separate ambient blob behind them. See NOTES.md. -->
    <div class="hero-ambient" />
    <canvas ref="storyCanvas" class="hero-canvas" />

    <!-- Content overlay -->
    <div class="content" :class="{ visible: contentVisible }">
      <div class="brand">MIVE</div>

      <!-- tagline-sub removed (see WELCOME_HERO_PROTOTYPE_NOTES.md) -->

      <!-- tagline-main typewriter removed (see WELCOME_HERO_PROTOTYPE_NOTES.md) -->

      <!-- "写一句" / danmaku entry point — commented out, see WELCOME_HERO_PROTOTYPE_NOTES.md
      <button
        class="write-quote-btn"
        @click="showQuoteModal = true"
      >
        {{ $t('welcome.writeQuote') }}
      </button>
      -->
    </div>

    <!-- Enter button — independent, fixed to the bottom-right, visibility tied only to contentVisible -->
    <button
      class="enter-btn"
      :class="{ visible: contentVisible }"
      @click="router.push('/worlds')"
    >
      {{ $t('welcome.enter') }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
// import { listWelcomeQuotes } from '../api/welcomeQuotes' // danmaku removed, see WELCOME_HERO_PROTOTYPE_NOTES.md
// import QuoteModal from '../components/QuoteModal.vue' // danmaku removed, see WELCOME_HERO_PROTOTYPE_NOTES.md

/* Danmaku-only interfaces — commented out with the danmaku feature, see WELCOME_HERO_PROTOTYPE_NOTES.md
interface QuoteItem {
  id: string
  content: string
  username: string
}

interface DanmakuItem {
  id: string
  content: string
  top: string
  speed: number
  delay: number
  color: string
  opacity: number
  fontSize: number
}
*/

type RGB = [number, number, number]

const router = useRouter()
const contentVisible = ref(false)
const isLeaving = ref(false)

/* Quotes / Danmaku — commented out, see WELCOME_HERO_PROTOTYPE_NOTES.md
const quotes = ref<QuoteItem[]>([])
const defaultQuotesAll: QuoteItem[] = [
  { id: 'd1', content: '每个世界都值得被铭记', username: '系统' },
  { id: 'd2', content: '想象力是唯一的边界', username: '系统' },
  { id: 'd3', content: '在这里，故事永远继续', username: '系统' },
  { id: 'd4', content: '遇见另一个自己', username: '系统' },
  { id: 'd5', content: 'Every world deserves to be remembered', username: 'System' },
  { id: 'd6', content: 'Imagination is the only boundary', username: 'System' },
  { id: 'd7', content: 'Here, stories never end', username: 'System' },
  { id: 'd8', content: 'Meet another version of yourself', username: 'System' },
  { id: 'd9',  content: 'すべての世界はRememberされる価値がある', username: 'システム' },
  { id: 'd10', content: '想象力は唯一の境界', username: 'システム' },
  { id: 'd11', content: 'ここで、物語は永遠に続く', username: 'システム' },
  { id: 'd12', content: 'もう一人の自分に出会う', username: 'システム' },
  { id: 'd13', content: '모든 세계는 기억될 가치가 있다', username: '시스템' },
  { id: 'd14', content: '상상력은 유일한 경계', username: '시스템' },
  { id: 'd15', content: '여기서 이야기는 영원히 계속된다', username: '시스템' },
  { id: 'd16', content: '또 다른 자신을 만나다', username: '시스템' },
]

const DANMAKU_COLORS = [
  'rgba(140, 160, 255, 0.7)',
  'rgba(180, 140, 255, 0.65)',
  'rgba(120, 200, 255, 0.65)',
  'rgba(160, 220, 200, 0.6)',
  'rgba(200, 160, 255, 0.68)',
  'rgba(140, 255, 200, 0.55)',
  'rgba(255, 180, 140, 0.6)',
  'rgba(180, 160, 255, 0.65)',
]

function buildDanmaku(source: QuoteItem[]): DanmakuItem[] {
  const items: DanmakuItem[] = []
  const totalSlots = Math.max(18, source.length * 2)
  for (let i = 0; i < totalSlots; i++) {
    const q = source[i % source.length]
    items.push({
      id: `dm-${i}-${q.id}`,
      content: q.content,
      top: (5 + Math.random() * 83) + '%',
      speed: 18 + Math.random() * 16,
      delay: -(Math.random() * 30),
      color: DANMAKU_COLORS[Math.floor(Math.random() * DANMAKU_COLORS.length)],
      opacity: 0.4 + Math.random() * 0.25,
      fontSize: 0.7 + Math.random() * 0.4,
    })
  }
  return items
}

const displayDanmaku = computed(() => {
  const src = quotes.value.length > 0
    ? [...quotes.value, ...defaultQuotesAll]
    : defaultQuotesAll
  return buildDanmaku(src)
})
*/

// ============================================================
// PROTOTYPE — hero visual "story"
// Throwaway exploration for replacing the space/globe metaphor
// with one drawn from the product's real character-relationship
// graph. See NOTES.md next to this file.
// ============================================================

interface HeroNode { x: number; y: number; r: number; phase: number; hue: number }

const storyCanvas = ref<HTMLCanvasElement | null>(null)
let storyAnimFrame = 0
let storyResizeHandler: (() => void) | null = null

function buildHeroNodes(w: number, h: number, count: number): HeroNode[] {
  const cx = w / 2
  const cy = h * 0.46
  const spread = Math.min(w, h) * 0.34
  const nodes: HeroNode[] = []
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2 + Math.random() * 0.6
    const dist = (0.35 + Math.random() * 0.65) * spread
    nodes.push({
      x: cx + Math.cos(angle) * dist,
      y: cy + Math.sin(angle) * dist * 0.72,
      r: 3 + Math.random() * 3.5,
      phase: Math.random() * Math.PI * 2,
      hue: 250 + Math.random() * 70,
    })
  }
  return nodes
}

function buildHeroEdges(nodes: HeroNode[], maxDist: number): Array<[number, number]> {
  const edges: Array<[number, number]> = []
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[i].x - nodes[j].x
      const dy = nodes[i].y - nodes[j].y
      if (Math.sqrt(dx * dx + dy * dy) < maxDist) edges.push([i, j])
    }
  }
  return edges
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

// `rgbOverride` lets a caller swap the default per-node hue gradient for a flat
// rgb color (used by `story`'s highlighted-subgraph rendering, which must use the
// project's --accent color instead of a hardcoded hue). Omit it to keep the
// original hsla-hue look.
function drawNode(ctx: CanvasRenderingContext2D, n: HeroNode, alpha: number, scale = 1, rgbOverride?: RGB) {
  const r = n.r * scale
  const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 4)
  if (rgbOverride) {
    const [rr, gg, bb] = rgbOverride
    grd.addColorStop(0, `rgba(${rr}, ${gg}, ${bb}, ${alpha})`)
    grd.addColorStop(1, `rgba(${rr}, ${gg}, ${bb}, 0)`)
  } else {
    grd.addColorStop(0, `hsla(${n.hue}, 90%, 75%, ${alpha})`)
    grd.addColorStop(1, 'hsla(260, 90%, 60%, 0)')
  }
  ctx.fillStyle = grd
  ctx.beginPath()
  ctx.arc(n.x, n.y, r * 4, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = rgbOverride
    ? `rgba(${rgbOverride[0]}, ${rgbOverride[1]}, ${rgbOverride[2]}, ${Math.min(1, alpha + 0.3)})`
    : `hsla(${n.hue}, 95%, 88%, ${Math.min(1, alpha + 0.3)})`
  ctx.beginPath()
  ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
  ctx.fill()
}

function drawBubble(ctx: CanvasRenderingContext2D, x: number, y: number, alpha: number, t: number) {
  if (alpha <= 0.02) return
  ctx.fillStyle = `rgba(30, 20, 55, ${0.78 * alpha})`
  ctx.strokeStyle = `rgba(200, 180, 255, ${0.5 * alpha})`
  ctx.lineWidth = 1
  roundRect(ctx, x, y, 56, 24, 9)
  ctx.fill()
  ctx.stroke()
  for (let d = 0; d < 3; d++) {
    const dotPhase = (t * 3 + d * 0.6) % 2
    const dotAlpha = dotPhase < 1 ? dotPhase : 2 - dotPhase
    ctx.globalAlpha = alpha * (0.4 + dotAlpha * 0.6)
    ctx.fillStyle = 'rgba(220, 210, 255, 1)'
    ctx.beginPath()
    ctx.arc(x + 15 + d * 14, y + 12, 2.6, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1
}

// `activeRgb` tints the chip's border/text with an rgb color (used by `story` to
// mark the 1-3 tag-cloud chips currently drifting toward the speaking node).
function drawChip(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, alpha: number, activeRgb?: RGB) {
  if (alpha <= 0.02) return
  ctx.font = '13px "Noto Sans SC", sans-serif'
  const padX = 12
  const w = ctx.measureText(text).width + padX * 2
  const h = 26
  ctx.fillStyle = `rgba(40, 28, 70, ${0.65 * alpha})`
  ctx.strokeStyle = activeRgb
    ? `rgba(${activeRgb[0]}, ${activeRgb[1]}, ${activeRgb[2]}, ${0.75 * alpha})`
    : `rgba(190, 170, 255, ${0.55 * alpha})`
  ctx.lineWidth = activeRgb ? 1.4 : 1
  roundRect(ctx, x - w / 2, y - h / 2, w, h, h / 2)
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = activeRgb
    ? `rgba(${activeRgb[0]}, ${activeRgb[1]}, ${activeRgb[2]}, ${Math.min(1, 0.9 * alpha + 0.1)})`
    : `rgba(230, 222, 255, ${0.9 * alpha})`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, x, y + 1)
}

function easeOut(p: number) {
  return 1 - Math.pow(1 - Math.min(1, Math.max(0, p)), 3)
}

// --- Story — ambient tag cloud + relationship graph with turn-taking chat ---
//
// One-time intro: a brief "seed beat" (a placeholder work title, then a placeholder
// template name, each shown alone at dead center) stands in for MIVE's two real
// creation entry points — extract from a work / start from a preset template —
// followed by a "collect beat" (loose light particles converge on center from the
// viewport's edges, standing in for raw-material gathering like wiki scraping) and a
// brief center flash (the moment that raw material gets distilled into structured
// elements). The tag cloud then fades in, each chip flying out from dead center to its
// rim position — visually "born" from that flash — while the node graph assembles
// underneath. Then an endless "steady-state chat" loop: a random node
// "speaks", and it + its direct neighbors form a conversation's fixed highlighted
// subgraph (rendered in --accent) that persists across several back-and-forth turns
// before a new conversation picks a fresh speaker — mirroring the real chat picker's
// "defaults to continuing last round's participants" behavior. A pulse travels the
// highlighted edges each turn while 2-3 randomly chosen tags (not the ones nearest the
// speaker on screen — layout position carries no semantic relevance) drift toward the
// speaker and back. Rare "memory propagation" rounds swap the fast/cool pulse for a
// slow, heavy, warm one that leaves a lingering imprint on the node it reaches.
interface StoryTag { label: string; baseAngle: number; baseRadiusFactor: number; phase: number }

const STORY_TAG_CATEGORIES: Array<{ name: string; count: number }> = [
  { name: '场所', count: 2 },
  { name: '势力', count: 2 },
  { name: '规则', count: 1 },
  { name: '事件', count: 2 },
  { name: '物品', count: 2 },
  { name: '文化', count: 1 },
  { name: '其他', count: 1 },
]

function buildStoryTags(): StoryTag[] {
  const labels: string[] = ['常识']
  for (const { name, count } of STORY_TAG_CATEGORIES) {
    for (let i = 1; i <= count; i++) labels.push(`${name}${i}`)
  }
  const total = labels.length
  return labels.map((label, i) => ({
    label,
    baseAngle: (i / total) * Math.PI * 2 + (Math.random() - 0.5) * 0.2,
    baseRadiusFactor: 0.44 + Math.random() * 0.09,
    phase: Math.random() * Math.PI * 2,
  }))
}

function storyTagPos(tag: StoryTag, cx: number, cy: number, minWH: number, t: number) {
  const breathe = Math.sin(t * 0.5 + tag.phase) * 0.015
  const radius = minWH * (tag.baseRadiusFactor + breathe)
  return { x: cx + Math.cos(tag.baseAngle) * radius, y: cy + Math.sin(tag.baseAngle) * radius * 0.72 }
}

// ---- "Collect" beat (intro only): a handful of bare light points fly in from beyond
// the viewport's edges and converge on dead center, standing in for the raw-material
// gathering step (wiki scraping etc., see CLAUDE.md 世界观: wiki 子链接扫描) that
// precedes LLM extraction in the real product. Deliberately not built on `HeroNode`/
// `StoryTag` — these are throwaway decoration with no identity beyond their flight path.
interface CollectParticle { angle: number; startRadiusFactor: number; delay: number }

function buildCollectParticles(count = 20): CollectParticle[] {
  const particles: CollectParticle[] = []
  for (let i = 0; i < count; i++) {
    particles.push({
      angle: Math.random() * Math.PI * 2,
      startRadiusFactor: 0.7 + Math.random() * 0.35, // beyond the tag ring, at/past the viewport edge
      delay: Math.random() * 0.4, // staggers departure so the swarm doesn't move in lockstep
    })
  }
  return particles
}

// 0 -> 1 -> 0 envelope across a round's lifetime: eases in over the first 30%,
// holds at the peak through the middle, eases back out over the last 30%.
function approachEnvelope(age: number, dur: number): number {
  const p = age / dur
  if (p < 0.3) return easeOut(p / 0.3)
  if (p < 0.7) return 1
  if (p < 1) return 1 - easeOut((p - 0.7) / 0.3)
  return 0
}

// Fade-in / hold / fade-out envelope for the intro's seed-beat chips (see initStory's
// SEED_* timeline below) — fades in over `fadeIn`, holds at full opacity for `hold`,
// then fades out over `fadeOut`. Returns 0 before `start` and after the tail-out ends.
function seedChipAlpha(t: number, start: number, fadeIn: number, hold: number, fadeOut: number): number {
  const age = t - start
  if (age < 0) return 0
  if (age < fadeIn) return easeOut(age / fadeIn)
  if (age < fadeIn + hold) return 1
  if (age < fadeIn + hold + fadeOut) return 1 - easeOut((age - fadeIn - hold) / fadeOut)
  return 0
}

function hexToRgb(hex: string): RGB {
  const clean = hex.replace('#', '')
  const n = parseInt(clean, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

// Reads the project's --accent theme variable so the highlighted subgraph always
// matches the active theme instead of a hardcoded hue (see CLAUDE.md: 主题用项目 CSS 变量).
function getAccentRgb(): RGB {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
  if (raw.startsWith('#')) return hexToRgb(raw)
  const nums = raw.match(/[\d.]+/g)
  if (nums && nums.length >= 3) return [Number(nums[0]), Number(nums[1]), Number(nums[2])]
  return [152, 115, 247] // fallback, roughly matches the breeze theme's accent
}

function drawPulseDot(ctx: CanvasRenderingContext2D, x: number, y: number, rgb: RGB, alpha: number, radius: number) {
  const [r, g, b] = rgb
  const grd = ctx.createRadialGradient(x, y, 0, x, y, radius * 3.4)
  grd.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${alpha})`)
  grd.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`)
  ctx.fillStyle = grd
  ctx.beginPath()
  ctx.arc(x, y, radius * 3.4, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${Math.min(1, alpha + 0.35)})`
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()
}

let storyNodes: HeroNode[] = []
let storyEdges: Array<[number, number]> = []
let storyTags: StoryTag[] = []
let storyCollectParticles: CollectParticle[] = []

// The "常识" tag (always storyTags[0], see buildStoryTags) is not a vector-retrieved
// element like the rest — CLAUDE.md 事件&聊天 元素注入 says world commonsense is
// injected into every conversation via `cacheable_system_prefix`, unconditionally.
// So unlike the other tags (which sit on the ring and occasionally drift toward the
// speaker when picked by chance in startTurn), 常识 leaves the ring entirely once the
// first conversation starts and re-anchors at the centroid of whichever subgraph
// (speaker + neighbors) is currently highlighted — re-drifting only when a brand-new
// conversation picks a new subgraph, not every turn, since the subgraph itself is
// stable across turns within one conversation.
let ckTag: StoryTag | null = null
let ckPos = { x: 0, y: 0 }
let ckFrom = { x: 0, y: 0 }
let ckTo = { x: 0, y: 0 }
let ckTransitionStart = 0
let ckInitialized = false
const CK_TRANSITION_DURATION = 1

function initStory() {
  const canvas = storyCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const accentRgb = getAccentRgb()
  const memoryRgb: RGB = [255, 150, 84] // warm, deliberately theme-independent — must read as distinct from the cool accent pulse
  const collectRgb: RGB = [170, 150, 255] // neutral lavender — raw, un-"branded" material; the flash below is the moment it turns into --accent

  let w = 0
  let h = 0
  const resize = () => {
    const dpr = window.devicePixelRatio || 1
    w = window.innerWidth
    h = window.innerHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    storyNodes = buildHeroNodes(w, h, 9)
    storyEdges = buildHeroEdges(storyNodes, Math.min(w, h) * 0.3)
    storyTags = buildStoryTags()
    storyCollectParticles = buildCollectParticles()
    ckTag = storyTags[0]
    ckInitialized = false
  }
  resize()
  storyResizeHandler = resize
  // TODO: debounce this — not addressed this pass, also skips prefers-reduced-motion
  window.addEventListener('resize', resize)

  function neighborsOf(idx: number): number[] {
    const out: number[] = []
    for (const [a, b] of storyEdges) {
      if (a === idx) out.push(b)
      else if (b === idx) out.push(a)
    }
    return out
  }
  function edgeKey(a: number, b: number): string {
    return a < b ? `${a}-${b}` : `${b}-${a}`
  }

  // Where 常识 sits on the ring, same formula the intro/steady-state ring tags use —
  // only needed as the flight's start point for its very first hand-off from the ring
  // to the chat subgraph's centroid.
  function ckRingPos(t: number) {
    const cx = w / 2
    const cy = h * 0.46
    const minWH = Math.min(w, h)
    return storyTagPos(ckTag!, cx, cy, minWH, t)
  }

  function highlightCentroid(): { x: number; y: number } {
    let sx = 0
    let sy = 0
    highlightNodes.forEach(i => {
      sx += storyNodes[i].x
      sy += storyNodes[i].y
    })
    const n = highlightNodes.size || 1
    return { x: sx / n, y: sy / n }
  }

  function ckPosAt(t: number) {
    const age = t - ckTransitionStart
    const progress = Math.max(0, Math.min(1, age / CK_TRANSITION_DURATION))
    const eased = easeOut(progress)
    return {
      x: ckFrom.x + (ckTo.x - ckFrom.x) * eased,
      y: ckFrom.y + (ckTo.y - ckFrom.y) * eased,
    }
  }

  // ---- Seed beat: a run of placeholder chips at dead-center, each naming a source
  // medium MIVE can extract a world from (novel / comic / film / TV drama), plus a
  // final chip for starting from a preset template instead, before the tag cloud below
  // has any reason to exist. Plays once through the full list, then the existing
  // tag-cloud-diffuses-outward timeline takes over at t = SEED_DURATION.
  const SEED_MEDIA_LABELS = ['小说', '漫画', '电影', '电视剧', '模板']
  const SEED_FADE_IN = 0.15
  const SEED_HOLD = 0.5
  const SEED_FADE_OUT = 0.25
  const SEED_GAP = 0.1 // silence between one chip fading out and the next fading in
  const SEED_CHIP_SPAN = SEED_FADE_IN + SEED_HOLD + SEED_FADE_OUT
  const SEED_STARTS = SEED_MEDIA_LABELS.map((_, i) => i * (SEED_CHIP_SPAN + SEED_GAP))
  const SEED_DURATION = SEED_STARTS[SEED_STARTS.length - 1] + SEED_CHIP_SPAN + 0.2 // + settle beat before the collect beat starts

  // ---- Collect beat: bare light points converge on center, standing in for raw
  // material gathering (see CollectParticle above) ----
  const COLLECT_START = SEED_DURATION
  const COLLECT_DURATION = 1.15
  const COLLECT_MAX_DELAY = COLLECT_DURATION * 0.3 // caps buildCollectParticles' per-particle `delay` so every particle still has time to arrive

  // ---- Flash beat: a short pulse at center marks the raw material being distilled
  // into structured elements — the moment the tag cloud "is born" from ----
  const FLASH_START = COLLECT_START + COLLECT_DURATION
  const FLASH_DURATION = 0.3

  // ---- One-time tag/node intro timeline (seconds, relative to the end of the flash beat) ----
  const TAG_TIMELINE_START = FLASH_START + FLASH_DURATION
  const TAG_STAGGER = 0.1
  const TAG_FADE_DURATION = 1.3
  // Nodes only start flying out once every tag chip has finished arriving — the
  // relationship graph is built FROM the extracted elements, not alongside them.
  const TAG_SETTLE_AT = (storyTags.length - 1) * TAG_STAGGER + TAG_FADE_DURATION
  const NODE_START = TAG_SETTLE_AT + 0.3
  const NODE_ASSEMBLE_DURATION = 2.3
  const INTRO_DURATION = NODE_START + NODE_ASSEMBLE_DURATION + 0.5

  // ---- Steady-state chat loop state ----
  // A "conversation" is a run of turns among the same speaker + its direct neighbors
  // (the highlighted subgraph); it mirrors the real chat picker's "select_participants
  // defaults to continuing last round's participants" behavior (see CLAUDE.md 角色聊天).
  // A "turn" is one speaker's beat within that conversation.
  let phase: 'intro' | 'chat' = 'intro'
  let roundStart = 0
  let roundDuration = 4
  let roundKind: 'normal' | 'memory' = 'normal'
  let speakerIdx = 0
  let highlightNodes = new Set<number>()
  let highlightEdges = new Set<string>()
  let nearTagIdx = new Set<number>()
  let memoryTargetIdx = -1
  let roundsSinceMemory = 0
  let turnsInConversation = 0

  // Shared per-turn setup: rolls the (independent, unchanged) memory-propagation
  // chance, picks this turn's round duration, and re-randomizes which 2-3 tag chips
  // drift toward the speaker. Does NOT touch highlightNodes/highlightEdges/speakerIdx —
  // callers own those.
  function startTurn(t: number) {
    roundStart = t
    const others = Array.from(highlightNodes).filter(i => i !== speakerIdx)

    // Memory propagation is deliberately rare — it only fires once a minimum number
    // of normal rounds have passed, and even then only probabilistically. This counter
    // is independent of the conversation/turn structure below — every turn can trigger
    // it, regardless of whether it starts a new conversation.
    const wantsMemory = others.length > 0 && roundsSinceMemory >= 3 && Math.random() < 0.32
    if (wantsMemory) {
      roundKind = 'memory'
      memoryTargetIdx = others[Math.floor(Math.random() * others.length)]
      roundDuration = 5 + Math.random() * 1.4
      roundsSinceMemory = 0
    } else {
      roundKind = 'normal'
      memoryTargetIdx = -1
      roundDuration = 3.2 + Math.random() * 1.4
      roundsSinceMemory++
    }

    // 2-3 tag-cloud chips drift toward the speaker this turn. Picked purely at random —
    // on-screen node/tag positions are arranged for visual balance only and carry no
    // semantic meaning, so "closest on screen" would misleadingly imply "most relevant"
    // (the real product ranks relevance via vector search, not layout distance).
    // 常识 is excluded from this pool — it's not a per-turn retrieval candidate, see
    // the ckTag block above `initStory`.
    const pickCount = 2 + Math.floor(Math.random() * 2)
    const candidateIdx = storyTags.map((_, i) => i).filter(i => storyTags[i] !== ckTag)
    const shuffled = candidateIdx.sort(() => Math.random() - 0.5)
    nearTagIdx = new Set(shuffled.slice(0, pickCount))
  }

  // Starts a brand-new conversation: a fresh random speaker + its direct neighbors
  // become this conversation's fixed highlighted subgraph.
  function startConversation(t: number) {
    speakerIdx = Math.floor(Math.random() * storyNodes.length)
    const neighbors = neighborsOf(speakerIdx)
    highlightNodes = new Set([speakerIdx, ...neighbors])
    highlightEdges = new Set(neighbors.map(n => edgeKey(speakerIdx, n)))
    turnsInConversation = 0
    startTurn(t)

    // 常识 re-anchors to the new subgraph's centroid — only here, on a fresh
    // conversation, never on continueConversation's mid-conversation speaker swaps.
    // The very first call (intro -> chat handoff) flies it in from its ring position;
    // every later call flies it from wherever it currently is.
    ckFrom = ckInitialized ? ckPosAt(t) : ckRingPos(t)
    ckTo = highlightCentroid()
    ckTransitionStart = t
    ckInitialized = true
  }

  // Advances the current conversation by one turn: the next speaker is whoever the
  // pulse just reached (a random member of the still-fixed highlighted subgraph, other
  // than whoever just spoke) — the subgraph itself does not change.
  function continueConversation(t: number) {
    const candidates = Array.from(highlightNodes).filter(i => i !== speakerIdx)
    if (candidates.length > 0) {
      speakerIdx = candidates[Math.floor(Math.random() * candidates.length)]
    }
    turnsInConversation++
    startTurn(t)
  }

  let t0 = 0
  let started = false

  function frame(ts: number) {
    if (!started) { t0 = ts; started = true }
    const t = (ts - t0) / 1000
    ctx!.clearRect(0, 0, w, h)
    const cx = w / 2
    const cy = h * 0.46
    const minWH = Math.min(w, h)

    if (phase === 'intro') {
      SEED_MEDIA_LABELS.forEach((label, i) => {
        const alpha = seedChipAlpha(t, SEED_STARTS[i], SEED_FADE_IN, SEED_HOLD, SEED_FADE_OUT)
        if (alpha > 0.02) drawChip(ctx!, cx, cy, label, alpha)
      })

      // Collect beat — bare light points converge on (cx, cy) from beyond the edges.
      const collectT = t - COLLECT_START
      if (collectT >= 0 && collectT < COLLECT_DURATION) {
        storyCollectParticles.forEach(p => {
          const delay = Math.min(p.delay, COLLECT_MAX_DELAY)
          const localT = collectT - delay
          if (localT < 0) return
          const dur = COLLECT_DURATION - delay
          const progress = Math.max(0, Math.min(1, localT / dur))
          const eased = easeOut(progress)
          const startRadius = minWH * p.startRadiusFactor
          const startX = cx + Math.cos(p.angle) * startRadius
          const startY = cy + Math.sin(p.angle) * startRadius * 0.72
          const x = startX + (cx - startX) * eased
          const y = startY + (cy - startY) * eased
          // quick fade-in, then fade back out as it nears center (about to be absorbed
          // into the flash below) rather than piling up as a solid dot at (cx, cy).
          const alpha = Math.min(1, localT * 4) * (1 - eased * 0.7)
          drawPulseDot(ctx!, x, y, collectRgb, alpha * 0.8, 1.6)
        })
      }

      // Flash beat — a short pulse at center marks raw material turning into elements.
      const flashT = t - FLASH_START
      if (flashT >= 0 && flashT < FLASH_DURATION) {
        const progress = flashT / FLASH_DURATION
        const flashAlpha = progress < 0.2 ? easeOut(progress / 0.2) : 1 - easeOut((progress - 0.2) / 0.8)
        const flashRadius = 6 + progress * 34
        drawPulseDot(ctx!, cx, cy, accentRgb, flashAlpha, flashRadius)
      }

      // Tag cloud — each chip flies out from dead center to its rim position while it
      // fades in, so it visually "emerges" from the flash above rather than appearing
      // in place. The lerp factor deliberately reuses the same eased fade-in progress
      // as `alpha` so position and opacity settle in lockstep.
      const introT = t - TAG_TIMELINE_START
      storyTags.forEach((tag, i) => {
        const progress = Math.max(0, Math.min(1, (introT - i * TAG_STAGGER) / TAG_FADE_DURATION))
        const alpha = easeOut(progress)
        if (alpha <= 0.02) return
        const target = storyTagPos(tag, cx, cy, minWH, t)
        const x = cx + (target.x - cx) * alpha
        const y = cy + (target.y - cy) * alpha
        drawChip(ctx!, x, y, tag.label, alpha)
      })

      // Character nodes get the same "flung out from dead center" treatment as the tag
      // chips above — they're born from the same extraction, just a beat later, once
      // the element cloud has finished settling.
      const nodeAlpha = easeOut(Math.max(0, Math.min(1, (introT - NODE_START) / NODE_ASSEMBLE_DURATION)))
      const edgeProgress = Math.max(0, Math.min(1, (introT - NODE_START - 0.3) / (NODE_ASSEMBLE_DURATION - 0.3)))
      const edgeCount = Math.floor(storyEdges.length * edgeProgress)
      const introNodePos = (n: HeroNode) => ({
        x: cx + (n.x - cx) * nodeAlpha,
        y: cy + (n.y - cy) * nodeAlpha,
      })
      ctx!.lineWidth = 1
      for (let i = 0; i < edgeCount; i++) {
        const [a, b] = storyEdges[i]
        const pa = introNodePos(storyNodes[a])
        const pb = introNodePos(storyNodes[b])
        ctx!.strokeStyle = `rgba(170, 150, 255, ${0.22 * nodeAlpha})`
        ctx!.beginPath()
        ctx!.moveTo(pa.x, pa.y)
        ctx!.lineTo(pb.x, pb.y)
        ctx!.stroke()
      }
      // Guard mirrors the tag chips' `alpha > 0.02` check above: `drawNode`'s core dot
      // has an unconditional `alpha + 0.3` floor (see drawNode) so it stays visible even
      // at alpha 0 — without this guard, all nodes collapse to (cx, cy) before NODE_START
      // and render as a persistent bright dot sitting on top of the seed-beat chip / tag
      // reveal, since introNodePos() maps every node to dead center while nodeAlpha is 0.
      if (nodeAlpha > 0.02) {
        storyNodes.forEach(n => {
          const pos = introNodePos(n)
          drawNode(ctx!, { ...n, x: pos.x, y: pos.y }, nodeAlpha)
        })
      }

      if (introT >= INTRO_DURATION) {
        phase = 'chat'
        startConversation(t)
      }
    } else {
      if (t - roundStart >= roundDuration) {
        // Same escalating-probability shape as the real chat picker's continuation
        // odds (CLAUDE.md 角色聊天: base=0.1 + count*0.05, capped at 1.0) — here it's
        // read as "the longer this conversation runs, the more likely it wraps up and
        // a new one starts" rather than "continues with the same participants".
        const endProbability = Math.min(1, 0.1 + turnsInConversation * 0.05)
        if (Math.random() < endProbability) {
          startConversation(t)
        } else {
          continueConversation(t)
        }
      }
      const roundAge = t - roundStart
      const speaker = storyNodes[speakerIdx]

      // Tag cloud — always rendered; the 2-3 tags picked in startTurn() drift toward
      // the speaker. 常识 is handled separately below (parked at the highlighted
      // subgraph's centroid, permanently accent-lit) instead of living on the ring.
      storyTags.forEach((tag, i) => {
        if (tag === ckTag) return
        const ring = storyTagPos(tag, cx, cy, minWH, t)
        const isNear = nearTagIdx.has(i)
        const approach = isNear ? approachEnvelope(roundAge, roundDuration) : 0
        const x = ring.x + (speaker.x - ring.x) * approach * 0.5
        const y = ring.y + (speaker.y - ring.y) * approach * 0.5
        const alpha = 0.78 + approach * 0.2
        drawChip(ctx!, x, y, tag.label, alpha, approach > 0.05 ? accentRgb : undefined)
      })

      // 常识 — always accent-lit (never plain), sitting at the current conversation's
      // subgraph centroid rather than the ring, to read as "always in context" instead
      // of "retrieved this turn" (see the ckTag block above initStory for why).
      ckPos = ckPosAt(t)
      drawChip(ctx!, ckPos.x, ckPos.y, ckTag!.label, 1, accentRgb)

      // Edges — dim by default, highlighted subgraph rendered in --accent.
      ctx!.lineWidth = 1
      for (const [a, b] of storyEdges) {
        const na = storyNodes[a]
        const nb = storyNodes[b]
        const isHi = highlightEdges.has(edgeKey(a, b))
        ctx!.strokeStyle = isHi
          ? `rgba(${accentRgb[0]}, ${accentRgb[1]}, ${accentRgb[2]}, 0.5)`
          : 'rgba(150, 140, 200, 0.08)'
        ctx!.beginPath()
        ctx!.moveTo(na.x, na.y)
        ctx!.lineTo(nb.x, nb.y)
        ctx!.stroke()
      }

      // Nodes — dim by default, highlighted subgraph brighter + --accent tinted.
      storyNodes.forEach((n, i) => {
        const breathe = Math.sin(t * 0.6 + n.phase) * 0.5 + 0.5
        if (highlightNodes.has(i)) {
          const isSpeaker = i === speakerIdx
          drawNode(ctx!, n, 0.75 + breathe * 0.2, isSpeaker ? 1.9 : 1.3, accentRgb)
        } else {
          drawNode(ctx!, n, 0.12 + breathe * 0.08, 0.85)
        }
      })

      if (roundKind === 'normal') {
        // Fast, cool pulses radiate from the speaker along every highlighted edge.
        const cycle = 1.1
        const fade = Math.min(1, roundAge * 2) * Math.max(0, 1 - Math.max(0, roundAge - (roundDuration - 0.5)) * 2)
        for (const nIdx of highlightNodes) {
          if (nIdx === speakerIdx) continue
          const progress = (roundAge % cycle) / cycle
          const nb = storyNodes[nIdx]
          const x = speaker.x + (nb.x - speaker.x) * progress
          const y = speaker.y + (nb.y - speaker.y) * progress
          drawPulseDot(ctx!, x, y, accentRgb, 0.85 * fade, 2.4)
        }
      } else if (memoryTargetIdx >= 0) {
        // Rare "memory propagation" — a single slow, heavy, warm pulse that leaves
        // an imprint glow on the target node once it arrives. Deliberately far
        // slower/heavier than the normal pulse so it reads as a distinct, weighty event.
        const travelDuration = roundDuration * 0.62
        const travelProgress = Math.max(0, Math.min(1, roundAge / travelDuration))
        const target = storyNodes[memoryTargetIdx]
        const eased = easeOut(travelProgress)
        const x = speaker.x + (target.x - speaker.x) * eased
        const y = speaker.y + (target.y - speaker.y) * eased
        const travelAlpha = Math.min(1, roundAge * 1.2)
        drawPulseDot(ctx!, x, y, memoryRgb, 0.9 * travelAlpha, 4.2)

        if (travelProgress >= 1) {
          const sinceArrival = roundAge - travelDuration
          const imprintAlpha = Math.max(0, 1 - sinceArrival / Math.max(0.001, roundDuration - travelDuration))
          const grd = ctx!.createRadialGradient(target.x, target.y, 0, target.x, target.y, 26)
          grd.addColorStop(0, `rgba(${memoryRgb[0]}, ${memoryRgb[1]}, ${memoryRgb[2]}, ${0.5 * imprintAlpha})`)
          grd.addColorStop(1, `rgba(${memoryRgb[0]}, ${memoryRgb[1]}, ${memoryRgb[2]}, 0)`)
          ctx!.fillStyle = grd
          ctx!.beginPath()
          ctx!.arc(target.x, target.y, 26, 0, Math.PI * 2)
          ctx!.fill()
        }
      }

      // Speech bubble at the speaker, fading in/out across the round. Alternates sides
      // by turn parity so back-and-forth conversations read as back-and-forth rather
      // than a bubble stuck at a fixed offset.
      const bubbleAlpha = Math.min(1, roundAge * 2.2) * Math.max(0, 1 - Math.max(0, roundAge - (roundDuration - 0.6)) * 2.4)
      const bubbleOnLeft = turnsInConversation % 2 === 1
      const bubbleX = bubbleOnLeft ? speaker.x - 18 - 56 : speaker.x + 18
      drawBubble(ctx!, bubbleX, speaker.y - 30, bubbleAlpha, t)
    }

    storyAnimFrame = requestAnimationFrame(frame)
  }
  storyAnimFrame = requestAnimationFrame(frame)
}

let willChangeTimer: ReturnType<typeof setTimeout>

onMounted(async () => {
  // 等待字体加载完成后再显示内容，避免 FOUT（字体闪烁）
  // 加 2s 超时兜底，防止字体加载慢导致长时间白屏
  try {
    await Promise.race([
      document.fonts.ready,
      new Promise<void>(resolve => setTimeout(resolve, 2000)),
    ])
  } catch { /* 字体加载失败也继续显示 */ }

  contentVisible.value = true

  await nextTick()
  initStory()

  // 内容淡入过渡完成后释放 will-change，减少移动端 GPU 内存压力
  willChangeTimer = setTimeout(() => {
    const el = document.querySelector('.content') as HTMLElement | null
    if (el) el.style.willChange = 'auto'
  }, 2000)

  /* Danmaku quotes fetch — commented out with the danmaku feature, see WELCOME_HERO_PROTOTYPE_NOTES.md
  try {
    quotes.value = await listWelcomeQuotes()
  } catch { // 用默认感言
  }
  */
})

onUnmounted(() => {
  cancelAnimationFrame(storyAnimFrame)
  clearTimeout(willChangeTimer)
  if (storyResizeHandler) window.removeEventListener('resize', storyResizeHandler)
})
</script>

<style scoped>
.welcome {
  position: fixed;
  inset: 0;
  /* PROTOTYPE — fixed neutral backdrop, deliberately NOT tied to the active theme's
     --accent (decided 2026-07-03: background stays constant, only the graph/tags
     respond to theme). A faint dot-grid layer sits on top for texture. See NOTES.md. */
  background:
    radial-gradient(circle, rgba(255, 255, 255, 0.14) 1.5px, transparent 1.5px) 0 0 / 40px 40px,
    radial-gradient(ellipse at 50% 46%, #171726 0%, #0a0a12 45%, #030305 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: opacity 0.7s ease;
}

.welcome.leaving {
  opacity: 0;
}

.welcome::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 45%, rgba(255, 255, 255, 0.05) 0%, transparent 60%);
  animation: pulse-bg 6s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes pulse-bg {
  from { opacity: 0.6; transform: scale(1); }
  to   { opacity: 1;   transform: scale(1.08); }
}

/* ========== Danmaku Layer — commented out, see WELCOME_HERO_PROTOTYPE_NOTES.md ==========
.danmaku-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.danmaku-item {
  position: absolute;
  top: var(--top);
  left: 100%;
  white-space: nowrap;
  animation: danmaku-scroll var(--duration) linear infinite;
  animation-delay: var(--delay);
  color: var(--color);
  opacity: var(--opacity);
}

.danmaku-text {
  font-family: 'Noto Serif SC', serif;
  font-size: var(--font-size);
  letter-spacing: 0.15em;
  text-shadow: 0 0 8px rgba(100, 60, 200, 0.15);
}

@keyframes danmaku-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(calc(-100vw - 100%)); }
}
*/

/* ========== PROTOTYPE — hero visual "story" ========== */
.hero-ambient {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.hero-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
  pointer-events: none;
}

/* ========== Content ========== */
.content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  opacity: 0;
  transition: opacity 0.8s ease;
  will-change: opacity;
}

.content.visible {
  opacity: 1;
}

/* MIVE brand mark. Renders directly in its final small, top-anchored state — no
   center-to-top settle animation (see WELCOME_HERO_PROTOTYPE_NOTES.md). `position:
   fixed` keeps it decoupled from `.content`'s flex flow. Only `opacity` animates, so
   the mark still fades in once `.content` becomes visible. */
.brand {
  position: fixed;
  top: 40px;
  left: 50%;
  z-index: 3;
  transform: translate(-50%, 0);
  font-family: 'Orbitron', 'DM Serif Display', 'Noto Serif SC', serif;
  font-size: clamp(1.1rem, 2.2vw, 1.6rem);
  font-weight: 700;
  letter-spacing: 0.3em;
  color: #e8e0ff;
  text-shadow:
    0 0 40px rgba(160, 120, 255, 0.5),
    0 0 80px rgba(100, 60, 220, 0.25);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.8s ease 0.3s;
}

.content.visible .brand {
  opacity: 1;
}

/* .tagline-sub removed (see WELCOME_HERO_PROTOTYPE_NOTES.md) */

/* .tagline-main typewriter removed (see WELCOME_HERO_PROTOTYPE_NOTES.md) */

/* "写一句" / danmaku entry point — commented out, see WELCOME_HERO_PROTOTYPE_NOTES.md
.write-quote-btn {
  margin-top: 16px;
  padding: 6px 20px;
  font-family: 'Noto Serif SC', serif;
  font-size: 0.8rem;
  letter-spacing: 0.2em;
  color: rgba(200, 180, 255, 0.5);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color 0.3s ease;
  outline: none;
}

.write-quote-btn:hover {
  color: rgba(200, 180, 255, 0.85);
}
*/

/* Independent, fixed to the bottom-right — visibility is tied only to `contentVisible`
   (the same fade the rest of the content used to share), never to the hero animation's
   progress. The user can click through to /worlds at any time. */
.enter-btn {
  position: fixed;
  right: 5vw;
  bottom: 6vh;
  padding: 8px 24px;
  font-family: 'Noto Serif SC', serif;
  font-size: 0.9rem;
  font-weight: 700;
  letter-spacing: 0.35em;
  color: rgba(220, 200, 255, 1);
  background: rgba(20, 15, 40, 0.9);
  border: 1px solid var(--accent);
  border-radius: 2px;
  cursor: pointer;
  outline: none;
  z-index: 4;
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 0.8s ease, transform 0.8s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

.enter-btn.visible {
  opacity: 1;
  transform: translateY(0);
  animation: enter-btn-breathe 3s ease-in-out infinite;
}

@keyframes enter-btn-breathe {
  0%, 100% {
    box-shadow: 0 0 4px 0 var(--accent-glow);
  }
  50% {
    box-shadow: 0 0 14px 2px var(--accent-glow);
  }
}

/* Expanding pulse ring, layered on top of the ambient breathing glow above so the
   button reads as a clear call-to-action rather than blending into the corner. */
.enter-btn.visible::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  border-radius: inherit;
  border: 1px solid var(--accent);
  opacity: 0.7;
  pointer-events: none;
  animation: enter-btn-pulse-ring 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes enter-btn-pulse-ring {
  0% {
    transform: scale(1);
    opacity: 0.7;
  }
  70%, 100% {
    transform: scale(1.4);
    opacity: 0;
  }
}

.enter-btn:hover {
  color: #eee0ff;
  border-color: var(--accent-hover);
  background: rgba(30, 20, 60, 0.9);
}

.enter-btn.visible:active {
  transform: translateY(0) scale(0.97);
}
</style>
