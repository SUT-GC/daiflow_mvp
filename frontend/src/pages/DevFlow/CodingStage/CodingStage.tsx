import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import DiffViewer from '../../../components/DiffViewer/DiffViewer'
import { useCodingStage } from '../../../hooks/useCodingStage'
import { executeTodo, skipTodo, startReview } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { TaskStatus } from '../../../types/enums'
import './CodingStage.css'

export default function CodingStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const {
    task, todos, selectedTodo, setSelectedTodo, diff,
    todoSessionStatus, allDone, loadData, isStale,
    messages, sendMessage, streaming,
  } = useCodingStage(taskId)

  const handleExecute = async (todoId: string) => {
    setSelectedTodo(todoId)
    try {
      await executeTodo(todoId)
    } catch (err: any) {
      console.error('Failed to execute todo:', err)
    }
  }

  const handleSkip = async (todoId: string) => {
    try {
      await skipTodo(todoId)
      loadData()
    } catch (err: any) {
      console.error('Failed to skip todo:', err)
    }
  }

  const handleNextStage = async () => {
    if (!taskId) return
    try {
      await startReview(taskId)
      navigate(`/devflow/${taskId}/review`)
    } catch (err: any) {
      console.error('Failed to start review:', err)
    }
  }

  const readonly = task ? isStageReadonly(task.status, 4) : false

  // Only the first PENDING or FAILED todo (in seq order) is actionable
  const nextActionableId = todos.find(t => t.status === 0 || t.status === 3)?.id ?? null

  return (
    <StageLayout
      taskId={taskId!}
      task={task}
      currentStage={4}
      content={
        <div className="coding-split">
          {/* Left: Todo Timeline */}
          <div className="todo-panel">
            <div className="panel-header">{t('coding.todos_header')}</div>
            <div className="timeline-list">
              {todos.map((todo, i) => {
                const isDone = todo.status === 2
                const isRunning = todo.status === 1
                const isFailed = todo.status === 3
                const isSkipped = todo.status === 4
                const isSelected = selectedTodo === todo.id
                const isPending = todo.status === 0
                const isActionable = todo.id === nextActionableId

                const stateClass = isDone ? 's-done' : isRunning ? 's-running' : isFailed ? 's-failed' : isSkipped ? 's-skipped' : ''

                return (
                  <div
                    key={todo.id}
                    className={`tl-item ${stateClass} ${isSelected ? 's-active' : ''}`}
                    onClick={() => setSelectedTodo(todo.id)}
                  >
                    <div className="tl-track">
                      <div className="tl-node">
                        {isDone ? '✓' : isRunning ? '↻' : isFailed ? '!' : isSkipped ? '⏭' : ''}
                      </div>
                      {i < todos.length - 1 && <div className="tl-line" />}
                    </div>
                    <div className="tl-card">
                      <div className="tl-seq">#{String(todo.seq).padStart(2, '0')}</div>
                      <div className="tl-name">{todo.title}</div>
                      <div className="tl-status">
                        {isDone ? t('coding.status.done') : isRunning ? t('coding.status.running') : isFailed ? t('coding.status.failed') : isSkipped ? t('coding.status.skipped') : t('coding.status.pending')}
                      </div>
                      {isActionable && isPending && task && task.status < TaskStatus.REVIEWING && (
                        <div className="tl-btn-row">
                          <button
                            className="btn btn-primary btn-xs tl-run-btn"
                            onClick={(e) => { e.stopPropagation(); handleExecute(todo.id) }}
                          >
                            {t('coding.execute')}
                          </button>
                          <button
                            className="btn btn-ghost btn-xs"
                            onClick={(e) => { e.stopPropagation(); handleSkip(todo.id) }}
                          >
                            {t('coding.skip')}
                          </button>
                        </div>
                      )}
                      {isActionable && isFailed && task && task.status < TaskStatus.REVIEWING && (
                        <div className="tl-btn-row">
                          <button
                            className="btn btn-primary btn-xs tl-run-btn"
                            onClick={(e) => { e.stopPropagation(); handleExecute(todo.id) }}
                          >
                            {t('coding.retry')}
                          </button>
                          <button
                            className="btn btn-ghost btn-xs"
                            onClick={(e) => { e.stopPropagation(); handleSkip(todo.id) }}
                          >
                            {t('coding.skip')}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Right: Code Changes */}
          <div className="coding-center">
            {!selectedTodo ? (
              <div className="center-idle">
                <div className="idle-icon">◇</div>
                <div className="idle-text">{t('coding.select_todo')}</div>
                <div className="idle-hint">{t('coding.select_hint')}</div>
              </div>
            ) : (
              <div className="center-running">
                <div className="sec-bar">
                  {t('coding.code_changes')}
                  {todoSessionStatus === 1 && <div className="live-dot" />}
                </div>
                {todoSessionStatus === 1 && !diff && (
                  <div className="spinner-row" style={{ padding: '40px 0', justifyContent: 'center' }}>
                    <div className="spinner" />
                    {t('coding.writing_code')}
                  </div>
                )}
                {diff ? (
                  <DiffViewer
                    diffs={diff}
                    collapsed={collapsed}
                    onToggleFile={(path) => setCollapsed(prev => ({ ...prev, [path]: !prev[path] }))}
                  />
                ) : todoSessionStatus !== 1 && (
                  <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
                    {t('coding.no_changes')}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      }
      actions={
        allDone && !readonly ? (
          <button className="btn btn-primary" onClick={handleNextStage}>
            {t('coding.next_review')}
          </button>
        ) : undefined
      }
      chatTitle={t('coding.chat_title')}
      chatMessages={messages}
      chatOnSend={sendMessage}
      chatStreaming={streaming}
      isStale={isStale}
    />
  )
}
