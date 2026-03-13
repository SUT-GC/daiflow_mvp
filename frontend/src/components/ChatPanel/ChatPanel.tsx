import { useState, useRef, useEffect } from 'react'
import { useLocale } from '../../hooks/useLocale'
import type { ChatMessage } from '../../hooks/useStageChat'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'
import ToolGroupBlock from '../ToolGroupBlock/ToolGroupBlock'
import { groupChatToolEvents } from '../../utils/groupToolEvents'

/** Distance (px) from bottom to consider "near bottom" for auto-scroll. */
const SCROLL_NEAR_BOTTOM_PX = 80

/** Max visible lines before a user message is collapsed. */
const USER_MSG_COLLAPSE_LINES = 3

function CollapsibleUserMsg({ content }: { content: string }) {
  const lines = content.split('\n')
  const shouldCollapse = lines.length > USER_MSG_COLLAPSE_LINES
  const [collapsed, setCollapsed] = useState(shouldCollapse)

  return (
    <div>
      <div style={{
        whiteSpace: 'pre-wrap',
        ...(collapsed ? {
          display: '-webkit-box',
          WebkitLineClamp: USER_MSG_COLLAPSE_LINES,
          WebkitBoxOrient: 'vertical' as const,
          overflow: 'hidden',
        } : {}),
      }}>
        {content}
      </div>
      {shouldCollapse && (
        <button
          className="msg-toggle-btn"
          onClick={() => setCollapsed(c => !c)}
        >
          {collapsed ? '展开 ▾' : '收起 ▴'}
        </button>
      )}
    </div>
  )
}

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (text: string) => void
  streaming?: boolean
  title?: string
  disabled?: boolean
  style?: React.CSSProperties
}

export default function ChatPanel({ messages, onSend, streaming = false, title, disabled = false, style }: ChatPanelProps) {
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

  const isSendDisabled = disabled || streaming || !input.trim()

  const handleSend = () => {
    if (isSendDisabled) return
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
    <div className="chat-panel" style={style}>
      <div className="chat-header">
        <div className="dot-live" />
        {title || t('chat.default_title')}
      </div>
      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.map((msg, i) => {
          const toolGroups = msg.role === 'ai' ? groupChatToolEvents(msg.events || []) : []
          return (
            <div key={msg.id} className={`msg ${msg.role === 'user' ? 'user' : ''}`}>
              <div className={msg.role === 'ai' ? 'avatar avatar-ai' : 'avatar avatar-u'}>
                {msg.role === 'ai' ? 'AI' : 'U'}
              </div>
              <div className="bubble">
                {msg.content && (
                  msg.role === 'ai'
                    ? <MarkdownViewer content={msg.content} />
                    : <CollapsibleUserMsg content={msg.content} />
                )}
                {toolGroups.length > 0 && (
                  <div className="chat-tool-groups">
                    {toolGroups.map((group, j) => (
                      <ToolGroupBlock key={j} tools={group.tools} />
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
          disabled={disabled || streaming}
        />
        <button className="send-btn" onClick={handleSend} disabled={isSendDisabled}>
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>
        </button>
      </div>
    </div>
  )
}
