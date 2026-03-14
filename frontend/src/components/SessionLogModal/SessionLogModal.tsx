import { useMemo } from 'react'
import Modal from '../Modal/Modal'
import ToolGroupBlock from '../ToolGroupBlock/ToolGroupBlock'
import { groupLogBlocks } from '../../utils/groupToolEvents'
import { useSession } from '../../hooks/useSession'
import { useLocale } from '../../hooks/useLocale'
import type { TranslationKey } from '../../i18n'

export default function SessionLogModal({ sessionId, label, onClose }: { sessionId: string; label: string; onClose: () => void }) {
  const { status, logs, error } = useSession(sessionId)
  const { t } = useLocale()
  const STATUS_KEYS: TranslationKey[] = ['init.status.waiting', 'init.status.running', 'init.status.done', 'init.status.failed']

  const blocks = useMemo(() => groupLogBlocks(logs), [logs])

  return (
    <Modal open onClose={onClose} width={700}>
      <div className="modal-title">{label}</div>
      <div className="modal-sub">
        Session: <code>{sessionId}</code> — Status: <span className={`tag tag-${status === 2 ? 'green' : status === 3 ? 'red' : status === 1 ? 'amber' : 'dim'}`}>{t(STATUS_KEYS[status])}</span>
      </div>
      {error && <div className="session-log-error">{error}</div>}
      <div className="session-log-container">
        {blocks.length === 0 ? (
          <div className="session-log-empty">{t('init.no_logs')}</div>
        ) : (
          blocks.map((block, i) => {
            if (block.kind === 'text') {
              return <div key={i} className="log-block log-block-text">{block.content}</div>
            }
            if (block.kind === 'tool-group') {
              return <ToolGroupBlock key={i} tools={block.tools} />
            }
            if (block.kind === 'error') {
              return <div key={i} className="log-block log-block-error">{block.content}</div>
            }
            if (block.kind === 'status') {
              return <div key={i} className="log-block log-block-status">Status → {t(STATUS_KEYS[block.status])}</div>
            }
            return null
          })
        )}
      </div>
    </Modal>
  )
}
