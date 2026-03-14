import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocale } from '../../hooks/useLocale'
import type { ChatMessage } from '../../hooks/useStageChat'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'
import ToolGroupBlock from '../ToolGroupBlock/ToolGroupBlock'
import { groupChatToolEvents } from '../../utils/groupToolEvents'

/** Distance (px) from bottom to consider "near bottom" for auto-scroll. */
const SCROLL_NEAR_BOTTOM_PX = 80

/** Max visible lines before a user message is collapsed. */
const USER_MSG_COLLAPSE_LINES = 3

function CollapsibleMsg({ content }: { content: string }) {
  const { t } = useLocale()
  const lines = content.split('\n')
  const shouldCollapse = lines.length > USER_MSG_COLLAPSE_LINES
  const [collapsed, setCollapsed] = useState(shouldCollapse)

  return (
    <div className="collapsible-msg">
      <div className={`collapsible-msg-body ${collapsed ? 'clamped' : ''}`}>
        <MarkdownViewer content={content} />
      </div>
      {shouldCollapse && (
        <button
          className="msg-toggle-btn"
          onClick={() => setCollapsed(c => !c)}
        >
          {collapsed ? t('chat.expand') : t('chat.collapse')}
        </button>
      )}
    </div>
  )
}

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (text: string) => void
  /** True when AI is actively generating: initial session running or user chat streaming. */
  responding?: boolean
  title?: string
  disabled?: boolean
  style?: React.CSSProperties
}

export default function ChatPanel({ messages, onSend, responding = false, title, disabled = false, style }: ChatPanelProps) {
  const { t } = useLocale()
  const [input, setInput] = useState('')
  const messagesRef = useRef<HTMLDivElement>(null)

  const isNearBottomRef = useRef(true)

  const handleScroll = () => {
    if (!messagesRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = messagesRef.current
    isNearBottomRef.current = scrollHeight - scrollTop - clientHeight < SCROLL_NEAR_BOTTOM_PX
  }

  useEffect(() => {
    if (messagesRef.current && isNearBottomRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [messages])

  const isSendDisabled = disabled || responding || !input.trim()

  const handleSend = useCallback(() => {
    if (disabled || responding || !input.trim()) return
    onSend(input.trim())
    setInput('')
  }, [disabled, responding, input, onSend])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="chat-panel" style={style}>
      <div className="chat-header">
        <div className="dot-live" />
        {title || t('chat.default_title')}
      </div>
      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.map((msg, i) => {
          const toolGroups = msg.role === 'ai' ? groupChatToolEvents(msg.events || []) : []
          const isLastAi = msg.role === 'ai' && i === messages.length - 1
          const isAiStreaming = isLastAi && responding
          const isAiDone = msg.role === 'ai' && msg.done === true

          return (
            <div key={msg.id} className={`msg ${msg.role === 'user' ? 'user' : ''}`}>
              <div className={msg.role === 'ai' ? 'avatar avatar-ai' : 'avatar avatar-u'}>
                {msg.role === 'ai' ? 'AI' : 'U'}
              </div>
              <div className="bubble">
                {msg.content && (
                  msg.role === 'user'
                    ? <CollapsibleMsg content={msg.content} />
                    : <MarkdownViewer content={msg.content} />
                )}
                {toolGroups.length > 0 && (
                  <div className="chat-tool-groups">
                    {toolGroups.map((group, j) => (
                      <ToolGroupBlock key={j} tools={group.tools} />
                    ))}
                  </div>
                )}
                {/* AI message status indicator */}
                {msg.role === 'ai' && (
                  <div className="msg-status">
                    {isAiStreaming ? (
                      <span className="msg-status-spinner" title="AI responding..." />
                    ) : isAiDone && msg.content ? (
                      <svg className="msg-status-check" width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path d="M3 7L6 10L11 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="chat-input-row">
        <textarea
          className="chat-input"
          placeholder={disabled ? '' : t('chat.placeholder')}
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || responding}
        />
        <button className="send-btn" onClick={handleSend} disabled={isSendDisabled}>
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>
        </button>
      </div>
    </div>
  )
}
