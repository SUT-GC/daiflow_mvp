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
import '../DevFlow.css'
import './CodingStage.css'

export default function CodingStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const {
    task, todos, selectedTodo, setSelectedTodo, diff,
    todoSessionStatus, logs, loadData, allDone,
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
      <Topbar title={task.name} branch={task.branch} backTo="/tasks" backLabel={t('nav.tasks')} />
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
                    {isPending && !isRunning && (
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
          {allDone && (
            <div style={{ padding: '12px' }}>
              <button className="btn btn-primary" style={{ width: '100%' }} onClick={handleNextStage}>
                {t('coding.next_review')}
              </button>
            </div>
          )}
        </div>

        {/* Center: Log + Diff */}
        <div className="coding-center">
          {!selectedTodo ? (
            <div className="center-idle">
              <div className="idle-icon">◇</div>
              <div className="idle-text">{t('coding.select_todo')}</div>
              <div className="idle-hint">{t('coding.select_hint')}</div>
            </div>
          ) : (
            <div className="center-running">
              {/* Log area */}
              <div className="log-area">
                <div className="sec-bar">
                  {t('coding.execution_log')}
                  {todoSessionStatus === 1 && <div className="live-dot" />}
                </div>
                <div className="log-lines">
                  {logs.filter(e => e.type !== 'user_message' && e.type !== 'compact').map((event, i) => (
                    <div key={i} className="log-line">
                      <span className="log-ts">{event.ts ? new Date(event.ts).toLocaleTimeString() : ''}</span>
                      {event.type === 'text_delta' && <span className="l-info">{event.content}</span>}
                      {event.type === 'tool_call' && <span className="l-write">[tool] {event.tool_name}</span>}
                      {event.type === 'tool_result' && <span className="l-read">[result] {(event.content || '').slice(0, 120)}</span>}
                      {event.type === 'thinking' && <span className="l-think">[think] {(event.content || '').slice(0, 80)}</span>}
                      {event.type === 'status_change' && <span className="l-done">[done]</span>}
                      {event.type === 'error' && <span className="l-err">[error] {event.content}</span>}
                    </div>
                  ))}
                  {todoSessionStatus === 1 && (
                    <div className="spinner-row">
                      <div className="spinner" />
                      {t('coding.writing_code')}
                    </div>
                  )}
                </div>
              </div>

              {/* Diff area */}
              {diff && (
                <div className="diff-area">
                  <div className="sec-bar">{t('coding.code_changes')}</div>
                  <DiffViewer
                    diffs={diff}
                    collapsed={collapsed}
                    onToggleFile={(path) => setCollapsed(prev => ({ ...prev, [path]: !prev[path] }))}
                  />
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
        />
      </div>
    </div>
  )
}
