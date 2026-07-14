import { ref, h } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useNotification } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { generateCharactersAsync, getGenerationStatus } from '@/api/worlds'
import { listCharacters } from '@/api/characters'
import { usePoll } from './usePoll'
import { useTabNotification } from './useTabNotification'

export function useProposalManagement(worldId: string, onCompleted?: () => Promise<void>) {
  const message = useMessage()
  const notification = useNotification()
  const router = useRouter()
  const { t } = useI18n()
  const generating = ref(false)
  const { start: startPoll, stop: stopPoll } = usePoll()
  const { notifyOnce } = useTabNotification()

  function showResultNotify(type: 'success' | 'error', title: string, bodyText: string) {
    // notif/remove 互相引用，通过变量闭包实现
    let notif: ReturnType<typeof notification.create> | null = null

    const remove = router.afterEach((to) => {
      if (to.path.match(/^\/world\//)) {
        notif?.destroy()
        notif = null
        remove()
      }
    })

    notif = notification.create({
      type,
      title,
      content: () => h('span', {}, [
        bodyText,
        ' ',
        h('a', {
          href: `/world/${worldId}`,
          style: { color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' },
          onClick: (e: MouseEvent) => {
            e.preventDefault()
            notif?.destroy()
            notif = null
            remove()
            router.push(`/world/${worldId}`)
          },
        }, t('createWorld.goToWorld')),
      ]),
      duration: 0,
      closable: true,
      onClose: () => { remove() },
    })
  }

  async function onGenerateCharacters(scale?: string) {
    generating.value = true
    stopPoll()
    try {
      await generateCharactersAsync(worldId, scale)

      startPoll(
        async () => {
          const { status } = await getGenerationStatus(worldId)
          if (status === 'completed') {
            generating.value = false
            const characters = await listCharacters(worldId)
            showResultNotify('success', t('createWorld.charGenDoneTitle'), t('createWorld.charGenSuccess', { n: characters.length }))
            notifyOnce('generation', '✅ 角色生成成功')
            if (onCompleted) await onCompleted()
            return true
          }
          if (status === 'failed') {
            generating.value = false
            showResultNotify('error', t('createWorld.charGenFailedTitle'), t('createWorld.charGenFailed'))
            notifyOnce('generation-fail', '❌ 角色生成失败')
            return true
          }
          return false
        },
        5000,
        1800000,
        () => { generating.value = false },
      )
    } catch (e) {
      message.error(t('createWorld.createFailed') + ': ' + (e as Error).message)
      generating.value = false
    }
  }

  return {
    generating,
    onGenerateCharacters,
  }
}
