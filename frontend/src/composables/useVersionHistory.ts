import { ref, toValue, type Ref, type MaybeRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage, useDialog } from 'naive-ui'
import { listVersions, rollbackVersion, updateVersionName, deleteVersion, createVersion, updateVersionSnapshot } from '@/api/versions'
import { parseApiError } from '@/utils/apiError'
import type { WorldVersion } from '@/types/version'

export function useVersionHistory(worldId: MaybeRef<string>) {
  const { t } = useI18n()
  const message = useMessage()
  const dialog = useDialog()

  const versions = ref<WorldVersion[]>([])
  const loading = ref(false)
  const creating = ref(false)
  const updating = ref(false)

  async function loadVersions() {
    loading.value = true
    try {
      versions.value = await listVersions(toValue(worldId))
      versions.value.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    } catch {
      // ignore
    } finally {
      loading.value = false
    }
  }

  function onRollback(versionId: string) {
    dialog.warning({
      title: t('version.rollbackTitle'),
      content: t('version.rollbackConfirm'),
      positiveText: t('version.confirmRollback'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        try {
          await rollbackVersion(toValue(worldId), versionId)
          message.success(t('version.rollbackSuccess'))
          await loadVersions()
        } catch (e) {
          message.error(t('version.rollbackFailed', { msg: parseApiError(e, t) }))
        }
      },
    })
  }

  async function renameVersion(versionId: string, name: string | null) {
    const trimmed = name?.trim() || null
    try {
      const updated = await updateVersionName(toValue(worldId), versionId, trimmed)
      versions.value = versions.value.map((ver) => (ver.id === versionId ? updated : ver))
      message.success(t('version.nameUpdated'))
    } catch (e) {
      message.error(t('version.nameUpdateFailed', { msg: parseApiError(e, t) }))
    }
  }

  async function onCreateVersion() {
    creating.value = true
    try {
      const newVersion = await createVersion(toValue(worldId))
      versions.value = [newVersion, ...versions.value]
      message.success(t('version.createSuccess'))
    } catch (e) {
      message.error(t('version.createFailed', { msg: parseApiError(e, t) }))
    } finally {
      creating.value = false
    }
  }

  async function onUpdateSnapshot(versionId: string) {
    updating.value = true
    try {
      const updated = await updateVersionSnapshot(toValue(worldId), versionId)
      versions.value = versions.value.map((ver) => (ver.id === versionId ? updated : ver))
      message.success(t('version.updateSnapshotSuccess'))
    } catch (e) {
      message.error(t('version.updateSnapshotFailed', { msg: parseApiError(e, t) }))
    } finally {
      updating.value = false
    }
  }

  function onDelete(versionId: string) {
    dialog.warning({
      title: t('version.deleteTitle'),
      content: t('version.deleteConfirm'),
      positiveText: t('version.confirmDelete'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        try {
          await deleteVersion(toValue(worldId), versionId)
          message.success(t('version.deleteSuccess'))
          await loadVersions()
        } catch (e) {
          message.error(t('version.deleteFailed', { msg: parseApiError(e, t) }))
        }
      },
    })
  }

  return {
    versions,
    loading,
    creating,
    updating,
    loadVersions,
    onRollback,
    renameVersion,
    onDelete,
    onCreateVersion,
    onUpdateSnapshot,
  }
}
