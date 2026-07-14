import { ref, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { generateOntology, buildGraph, getGraphTask } from '@/api/graph'
import { parseApiError } from '@/utils/apiError'
import type { GraphTask } from '@/api/graph'

export function useGraphBuild(worldId: string, onBuildCompleted?: () => void) {
  const { t } = useI18n()
  const graphStatus = ref<string>('idle')
  const graphBuildTaskId = ref<string | null>(null)
  const graphBuildProgress = ref(0)
  const graphBuildMessage = ref('')
  const graphBuilding = ref(false)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function onBuildGraph() {
    graphBuilding.value = true
    graphBuildMessage.value = t('graph.buildInitOntology')
    try {
      const ontology = await generateOntology(worldId)
      graphBuildMessage.value = t('graph.buildConstructGraph')
      const { task_id } = await buildGraph(worldId, ontology)
      graphBuildTaskId.value = task_id
      graphStatus.value = 'building'
      startPolling(task_id)
    } catch (e) {
      graphBuildMessage.value = t('graph.buildFailed', { msg: parseApiError(e, t) })
      graphBuilding.value = false
    }
  }

  function startPolling(taskId: string) {
    pollTimer = setInterval(async () => {
      try {
        const task: GraphTask = await getGraphTask(worldId, taskId)
        graphBuildProgress.value = task.progress
        graphBuildMessage.value = task.message
        if (task.status === 'completed') {
          graphStatus.value = 'completed'
          graphBuilding.value = false
          stopPolling()
          onBuildCompleted?.()
        } else if (task.status === 'failed') {
          graphStatus.value = 'failed'
          graphBuildMessage.value = task.error || t('graph.buildFailed', { msg: '' })
          graphBuilding.value = false
          stopPolling()
        }
      } catch {
        // Poll error, continue
      }
    }, 2000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  onUnmounted(stopPolling)

  return {
    graphStatus,
    graphBuildProgress,
    graphBuildMessage,
    graphBuilding,
    onBuildGraph,
  }
}
