<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Renders LLM-generated structured Markdown (headings/bold/lists) as sanitized HTML.
// Old plain-prose data with no Markdown syntax renders unchanged as a single <p>.
const props = defineProps<{
  text?: string | null
}>()

const html = computed(() => {
  const raw = props.text ?? ''
  if (!raw.trim()) return ''
  return DOMPurify.sanitize(marked.parse(raw, { async: false }) as string)
})
</script>

<template>
  <div class="markdown-text" v-html="html"></div>
</template>

<style scoped>
.markdown-text {
  /* inherits font-size/color/line-height from the caller's class */
}

.markdown-text :deep(p) {
  margin: 0 0 0.6em;
}

.markdown-text :deep(p:first-child) {
  margin-top: 0;
}

.markdown-text :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-text :deep(h1),
.markdown-text :deep(h2),
.markdown-text :deep(h3),
.markdown-text :deep(h4),
.markdown-text :deep(h5),
.markdown-text :deep(h6) {
  margin: 0.7em 0 0.35em;
  font-size: 1em;
  font-weight: 700;
  color: inherit;
  font-family: inherit;
}

.markdown-text :deep(h1:first-child),
.markdown-text :deep(h2:first-child),
.markdown-text :deep(h3:first-child),
.markdown-text :deep(h4:first-child),
.markdown-text :deep(h5:first-child),
.markdown-text :deep(h6:first-child) {
  margin-top: 0;
}

.markdown-text :deep(ul),
.markdown-text :deep(ol) {
  margin: 0 0 0.6em;
  padding-left: 1.4em;
}

.markdown-text :deep(ul:last-child),
.markdown-text :deep(ol:last-child) {
  margin-bottom: 0;
}

.markdown-text :deep(li) {
  margin-bottom: 0.2em;
}

.markdown-text :deep(li:last-child) {
  margin-bottom: 0;
}

.markdown-text :deep(strong) {
  font-weight: 700;
  color: inherit;
}

.markdown-text :deep(em) {
  font-style: italic;
}

.markdown-text :deep(code) {
  background: var(--bg-main, rgba(0, 0, 0, 0.05));
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.9em;
}

.markdown-text :deep(blockquote) {
  border-left: 3px solid rgba(0, 0, 0, 0.12);
  padding-left: 0.8em;
  color: var(--text-muted);
  margin: 0.5em 0;
}

.markdown-text :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.markdown-text :deep(a:hover) {
  text-decoration: underline;
}

.markdown-text :deep(hr) {
  border: none;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  margin: 0.6em 0;
}
</style>
