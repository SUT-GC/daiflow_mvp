import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../../components/Shell/Topbar'
import StageProgress from '../../../components/StageProgress/StageProgress'
import ChatPanel from '../../../components/ChatPanel/ChatPanel'
import DiffViewer from '../../../components/DiffViewer/DiffViewer'
import Loading from '../../../components/Loading/Loading'
import { useCodingStage } from '../../../hooks/useCodingStage'
import { executeTodo, startReview } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { TaskStatus } from '../../../types/enums'
import '../DevFlow.css'
import './CodingStage.css'

export default function CodingStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const {
    task, todos, selectedTodo, setSelectedTodo, diff,
    todoSessionStatus, allDone,
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

  const handleNextStage = async () => {
    if (!taskId) return
    try {
      await startReview(taskId)
      navigate(`/devflow/${taskId}/review`)
    } catch (err: any) {
      console.error('Failed to start review:', err)
    }
  }

  if (!task) return <Loading />

  return (
    <div id="page" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Topbar title={task.name} branch={task.branch} taskStatus={task.status} backTo="/tasks" backLabel={t('nav.tasks')} />
      <StageProgress taskId={taskId!} currentStage={3} taskStatus={task.status} />
      <div className="devflow-body">
        {/* Left: Todo Timeline */}
        <div className="todo-panel">
          <div className="panel-header">{t('coding.todos_header')}</div>
          <div className="timeline-list">
            {todos.map((todo, i) => {
              const isDone = todo.status === 2
              const isRunning = todo.status === 1
              const isFailed = todo.status === 3
              const isSelected = selectedTodo === todo.id
              const isPending = todo.status === 0

              return (
                <div
                  key={todo.id}
                  className={`tl-item ${isDone ? 's-done' : isRunning ? 's-running' : isFailed ? 's-failed' : ''} ${isSelected ? 's-active' : ''}`}
                  onClick={() => setSelectedTodo(todo.id)}
                >
                  <div className="tl-track">
                    <div className="tl-node">
                      {isDone ? '✓' : isRunning ? '↻' : isFailed ? '!' : ''}
                    </div>
                    {i < todos.length - 1 && <div className="tl-line" />}
                  </div>
                  <div className="tl-card">
                    <div className="tl-seq">#{String(todo.seq).padStart(2, '0')}</div>
                    <div className="tl-name">{todo.title}</div>
                    <div className="tl-status">
                      {isDone ? t('coding.status.done') : isRunning ? t('coding.status.running') : isFailed ? t('coding.status.failed') : t('coding.status.pending')}
                    </div>
                    {isPending && !isRunning && task.status < TaskStatus.REVIEWING && (
                      <button
                        className="btn btn-primary btn-xs tl-run-btn"
                        onClick={(e) => { e.stopPropagation(); handleExecute(todo.id) }}
                      >
                        {t('coding.execute')}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {allDone && task.status < TaskStatus.REVIEWING && (
            <div style={{ padding: '12px' }}>
              <button className="btn btn-primary" style={{ width: '100%' }} onClick={handleNextStage}>
                {t('coding.next_review')}
              </button>
            </div>
          )}
        </div>

        {/* Center: Code Changes */}
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

        {/* Right: Chat */}
        <ChatPanel
          messages={messages}
          onSend={sendMessage}
          streaming={streaming}
          title={t('coding.chat_title')}
          disabled={task.status >= TaskStatus.REVIEWING}
        />
      </div>
    </div>
  )
}
