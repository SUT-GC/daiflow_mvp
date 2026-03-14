import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import { useTodoStage } from '../../../hooks/useTodoStage'
import { startCoding, triggerTodo } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import type { TodoData } from '../../../api'
import './TodoStage.css'

export default function TodoStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { task, todos, status, messages, sendMessage, streaming, refreshSession } = useTodoStage(taskId)
  const [selectedTodo, setSelectedTodo] = useState<TodoData | null>(null)

  const handleRedecompose = async () => {
    if (!taskId) return
    await triggerTodo(taskId)
    refreshSession()
  }

  const handleStartCoding = async () => {
    if (!taskId) return
    try {
      await startCoding(taskId)
      navigate(`/devflow/${taskId}/coding`)
    } catch (err: any) {
      console.error('Failed to start coding:', err)
    }
  }

  const readonly = task ? isStageReadonly(task.status, 3) : false
  const isGenerating = status === 1 || streaming
  const startCodingDisabled = todos.length === 0 || isGenerating || readonly
  const redecomposeDisabled = isGenerating || readonly

  return (
    <>
      <StageLayout
        taskId={taskId!}
        task={task}
        currentStage={3}
        content={
          <div className="card todo-wrap">
            <div className="todo-card-title">
              {t('todo.title')}
              <span className="file-badge">todo.json</span>
              {todos.length > 0 && <span className="count-badge">{todos.length}</span>}
            </div>
            {todos.length > 0 ? (
              <div className="todo-items">
                {todos.map((todo, i) => (
                  <div
                    key={i}
                    className="card todo-item"
                    onClick={() => setSelectedTodo(todo)}
                  >
                    <div className="todo-seq">{String(todo.seq || i + 1).padStart(2, '0')}</div>
                    <div className="todo-title">{todo.title}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
                {status === 1 ? t('todo.decomposing') : t('todo.no_todos')}
              </div>
            )}
          </div>
        }
        actions={
          <>
            <button className="btn btn-primary" onClick={handleStartCoding} disabled={startCodingDisabled}>
              {t('todo.start_coding')}
            </button>
            <button className="btn btn-ghost" onClick={handleRedecompose} disabled={redecomposeDisabled}>
              {t('todo.redecompose')}
            </button>
          </>
        }
        chatTitle={t('todo.chat_title')}
        chatMessages={messages}
        chatOnSend={sendMessage}
        chatStreaming={streaming}
      />

      {/* Todo Detail Modal */}
      {selectedTodo && (
        <>
          <div className="overlay" onClick={() => setSelectedTodo(null)} />
          <div className="todo-modal">
            <div className="todo-modal-header">
              <span className="todo-modal-seq">{String(selectedTodo.seq || '').padStart(2, '0')}</span>
              <span className="todo-modal-title">{selectedTodo.title}</span>
              <button className="todo-modal-close" onClick={() => setSelectedTodo(null)}>×</button>
            </div>
            <div className="todo-modal-body">
              {selectedTodo.description}
            </div>
          </div>
        </>
      )}
    </>
  )
}
