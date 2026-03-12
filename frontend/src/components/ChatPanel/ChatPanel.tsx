import { useState, useRef, useEffect } from 'react'
import { useLocale } from '../../hooks/useLocale'
import type { ChatMessage } from '../../hooks/useStageChat'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (text: string) => void
  streaming?: boolean
  title?: string
}

export default function ChatPanel({ messages, onSend, streaming = false, title }: ChatPanelProps) {
  const { t } = useLocale()
  const [input, setInput] = useState('')
  const messagesRef = useRef<HTMLDivElement>(null)

  const isNearBottomRef = useRef(true)

  const handleScroll = () => {
    if (!messagesRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = messagesRef.current
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < 80
  }

  useEffect(() => {
    if (messagesRef.current && isNearBottomRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = () => {
    if (!input.trim() || streaming) return
    onSend(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div className="dot-live" />
        {title || t('chat.default_title')}
      </div>
      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.map((msg, i) => (
          <div key={msg.id} className={`msg ${msg.role === 'user' ? 'user' : ''}`}>
            <div className={msg.role === 'ai' ? 'avatar avatar-ai' : 'avatar avatar-u'}>
              {msg.role === 'ai' ? 'AI' : 'U'}
            </div>
            <div className="bubble">
              {msg.content && (
                msg.role === 'ai'
                  ? <MarkdownViewer content={msg.content} />
                  : <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
              )}
              {msg.events && msg.events.length > 0 && (
                <div className="log-block">
                  {msg.events.map((ev, j) => (
                    <div key={j} className="log-line">
                      {ev.type === 'tool_call' && (
                        <>
                          <span className="log-tool">tool</span>
                          <span>{ev.tool_name}({typeof ev.args === 'object' ? JSON.stringify(ev.args).slice(0, 80) : ev.args})</span>
                        </>
                      )}
                      {ev.type === 'tool_result' && (
                        <>
                          <span className="log-read">result</span>
                          <span>{(ev.content || '').slice(0, 100)}</span>
                        </>
                      )}
                      {ev.type === 'thinking' && (
                        <span style={{ color: 'var(--t2)', fontStyle: 'italic' }}>
                          {(ev.content || '').slice(0, 100)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {streaming && i === messages.length - 1 && msg.role === 'ai' && (
                <div className="typing-row">
                  <div className="typing-dot" />
                  <div className="typing-dot" />
                  <div className="typing-dot" />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="chat-input-row">
        <textarea
          className="chat-input"
          placeholder={t('chat.placeholder')}
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
        />
        <button className="send-btn" onClick={handleSend} disabled={streaming || !input.trim()}>
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>
        </button>
      </div>
    </div>
  )
}
