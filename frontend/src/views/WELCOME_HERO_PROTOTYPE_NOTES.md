# PROTOTYPE — welcome page hero visual

**Question being answered:** the welcome page's "space/galaxy + wireframe globe" visual
reads as an astronomy site, unrelated to what MIVE actually does (extract worldbuilding,
manage character relationships, chat with characters). Does swapping the metaphor to
"a glowing character-relationship network" (the same visual language as the real graph
page) read better, and which cut of it should we ship?

**Where the code lives:** all prototype code is inline in `WelcomePage.vue`, clearly
marked with `PROTOTYPE` comments — no new files besides this one. Switch variants via
`?variant=` on `/welcome`:

- `?variant=space` (or no param) — original, unchanged
- `?variant=network` — calm breathing relationship network, one node lights up with a
  chat bubble every ~3s. No literal narrative, just ambient mood.
- `?variant=story` — (updated 2026-07-03, first pass at turning the winning direction
  into something usable) a tag cloud (world-element categories + "常识") sits in a
  ring around the outer edge, always present — it represents the worldbuilding/common-
  sense context that backs every conversation. A relationship graph assembles in the
  center. The MIVE brand mark renders directly in its final small, top-anchored state
  from the moment it loads — there is no center-to-top shrink/rise animation (removed
  2026-07-03: `heroIntroSettled` and the `.brand`/`.brand.settled` split are gone,
  `.brand` is one fixed-position rule now, only its opacity fades in).

  Plays a one-time slow intro that opens with a brief "seed beat" — a placeholder
  work-title chip, then a placeholder template-name chip, each shown alone at dead
  center and fading out in turn — standing in for MIVE's two real creation entry
  points (extract from a work / start from a preset template) before the tag cloud has
  any reason to exist. (Updated 2026-07-03) The seed beat now hands off to a "collect"
  beat — ~20 bare light points fly in from beyond the viewport edges and converge on
  dead center over ~1.15s — standing in for the raw-material gathering step (wiki
  scraping etc.) that precedes LLM extraction in the real product, followed by a brief
  (~0.3s) expanding flash at center marking the moment that raw material gets
  distilled into structured elements. Only then does the tag cloud reveal begin, and
  each chip now flies out from dead center to its rim position while fading in
  (previously: faded in in place) — visually "born" from the flash — while the
  relationship graph assembles underneath as before. The whole intro is now ~1.45s
  longer than before this pass (collect + flash beats) before it falls into the
  endless "steady-state chat" loop, modeled as conversations made of several turns
  rather than fully independent rounds: a random node "speaks", and it + its direct
  neighbors become that conversation's fixed highlighted subgraph (rendered in the
  theme's `--accent` color while everything else dims); a pulse travels the
  highlighted edges each turn, and the speech bubble alternates sides by turn so it
  reads as back-and-forth. After each turn, an escalating "end probability"
  (`min(1, 0.1 + turnsInConversation * 0.05)` — the same shape as the real chat
  picker's continuation odds) decides whether the conversation keeps going with a new
  speaker drawn from the same highlighted subgraph, or wraps up and a fresh
  conversation starts with a new random speaker + neighborhood. The 2-3 tag chips that
  drift toward the speaker each turn are now chosen purely at random from the full tag
  set, not by angular/on-screen distance to the speaker — screen position is
  decorative only and was misleadingly implying "closer on screen = more relevant"
  (the real product ranks relevance via vector search). Rare "memory propagation"
  rounds (sparse, deliberately infrequent, independent of the conversation/turn
  structure) swap the fast/cool pulse for a slow, heavy, warm-colored one that leaves
  a lingering imprint on the node it reaches — mirroring that memory propagation is
  off by default and only major memories trigger it.

  (Updated 2026-07-03, second pass) Node/edge assembly now waits until every tag chip
  has fully arrived at its rim position before it starts — previously the two phases
  overlapped. Character nodes get the same "flung out from dead center while fading in"
  treatment as the tag chips (`introNodePos` lerps each node from `(cx, cy)` to its
  final position using the same eased `nodeAlpha`, and edges are drawn between the
  in-flight positions, not the final ones) — visually, both elements and characters are
  "born" from the same central extraction moment, just one beat apart. MIVE also no
  longer has a fade/settle transition at all — it renders at its final small top-left
  position and size from the very first frame (no center-to-top movement to skip).

**Backdrop (2026-07-03, superseded twice):** first pass made `.welcome`/`.welcome::before`
tint toward the active theme's `--accent` (`color-mix(in srgb, var(--accent) X%, black)`).
**This was reversed the same day** — decided the backdrop should NOT react to theme at
all, only the graph/tag highlights and chrome buttons should. `.welcome` is now a fixed,
theme-independent radial vignette (`#171726 → #0a0a12 → #030305`) with a faint fixed-size
dot-grid layer on top (`radial-gradient(circle, rgba(255,255,255,0.14) 1.5px, transparent
1.5px) 0 0 / 40px 40px`, tuned down from an initial too-loud 0.35/2px pass) for texture.
`.welcome::before`'s breathing pulse is neutral white now too, not accent-tinted. The
`.hero-glow` layer (a single soft white blob behind the network, a short-lived
experiment) was tried and then removed outright — the network/tags' own canvas glow is
the only light source now, `.hero-ambient` is an empty wrapper with no children.
`ThemeToggle` was briefly unhidden on `/welcome` in `App.vue` (was `v-if="!isWelcome"`) so
the 7-color/light-dark switcher was reachable there too — even though it no longer
affected the backdrop, it still affected the graph's highlight color and the toolbar
buttons' `--accent`. **Reversed 2026-07-03**: the whole `.global-toolbar` (`GuideButton`,
`DMEntryButton`, `LanguageToggle`, `ThemeToggle`) is back to `v-if="!isWelcome"` — the
top-right buttons read as clutter on the welcome page. `.enter-btn` was also shrunk
(`padding: 14px 42px` → `8px 24px`, `font-size: 1.4rem` → `0.9rem`, `letter-spacing: 0.5em`
→ `0.35em`) — it read as too large/heavy sitting alone in the bottom-right corner.

**Enter button border (2026-07-04):** the animated 10-color rainbow chase border was
replaced with a static `1px solid var(--accent)` border plus a slow `--accent-glow`
breathing box-shadow (`enter-btn-breathe`, 3s ease-in-out). Rationale: the rainbow
border contradicted the 2026-07-03 decision that only graph/tag highlights and chrome
buttons should react to theme (not go fully theme-independent, and not be decorative
rainbow chrome) — and it read as gimmicky next to the already-shrunk, understated
button. Hover now darkens the fill and switches border to `--accent-hover` instead of
relying on a pseudo-element overlay trick.

A floating switcher (dev-only, bottom-center) cycled variants with arrows / ←/→ keys.
It force-reloaded the page on switch so each variant's canvas init/cleanup ran cleanly.
(Removed 2026-07-03, see TODO item 4 below.)

**Verdict:** `story` wins (decided 2026-07-03). `space` and `network` are discarded.

**Clean-up TODO:**
1. [done 2026-07-03] Deleted the `space` variant: `.galaxy`/`.planet-zone` template
   blocks, `initGalaxy`, `drawGalaxyBackground`, `startGalaxyFxLoop`,
   `handleGalaxyResize`, `latitudeRings`, `orbitalSparkles`, `galaxyBgCanvas`/
   `galaxyFxCanvas` refs, and the matching CSS (`.galaxy*`, `.planet-*`,
   `@keyframes sphere-spin`/`glow-pulse` etc).
2. [done 2026-07-03] Deleted the `network` variant: `initNetwork`, `networkCanvas` ref,
   its resize handler (`networkResizeHandler`), `heroNodes`/`heroEdges`. Kept the shared
   helpers `story` still uses: `buildHeroNodes`/`buildHeroEdges`/`drawNode`/`drawBubble`/
   `roundRect`/`easeOut`.
3. Delete `drawChip` only if `story` stops using it — currently still used for the
   tag cloud (both the intro-phase reveal and the steady-state chat loop).
4. [done 2026-07-03] Removed the `variant` computed, `VARIANT_KEYS`/`VARIANT_LABELS`,
   `cycleVariant`, `handleVariantKeydown`, `isDev`, the `.proto-switcher` template block
   + CSS, and the now-unused `route`/`useRoute`/`computed` imports. `story` is now the
   only hero, unconditionally mounted (no more `v-if="variant === ..."`) — `initStory()`
   runs unconditionally in `onMounted`, `onUnmounted` only cleans up `story`'s own
   animation frame + resize listener.
5. Polish `story`'s code before it's real production code (it was written under
   prototype constraints):
   - `STORY_TAG_CATEGORIES` (场所/势力/规则/事件/物品/文化/其他 + "常识") are hardcoded
     Chinese. The site supports 5 locales (zh-CN/zh-TW/en/ja/ko per CLAUDE.md) —
     decide whether to i18n these strings or replace them with language-agnostic
     glyphs/icons.
   - Resize listener is a naive immediate rebuild (no debounce) — fine at prototype
     scale, worth debouncing like `handleGalaxyResize` did for the old code.
   - No `prefers-reduced-motion` handling — check if the rest of the app respects it
     and match.
   - Node/tag counts, positions, and round/pulse timings (`INTRO_DURATION`, tag
     count/radius, round duration ranges, memory-round probability, etc.) were
     eyeballed, not tuned.
   - MIVE position/size, the enter button size, and the backdrop have now been
     checked and tuned in-browser (not just eyeballed in code) across this pass.
     The tag cloud's own density/spread and the memory-propagation animation's
     exact timing are still just the original eyeballed values — worth a closer
     look before this is real production code.
6. Verify `/welcome` end-to-end (fresh load, resize, Enter → /auth still works), then
   delete this NOTES.md file.
