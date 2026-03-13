import { useState, useRef, useEffect } from 'react'
import { useLocale } from '../../hooks/useLocale'
import type { ChatMessage } from '../../hooks/useStageChat'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (text: string) => void
  streaming?: boolean
  title?: string
  disabled?: boolean
  style?: React.CSSProperties
}

type ToolEntry = { toolName: string; args?: any; result?: string }

/** Group consecutive tool/thinking events into collapsible tool-groups */
function groupEvents(events: any[]): Array<{ kind: 'tool-group'; tools: ToolEntry[] }> {
  if (!events || events.length === 0) return []
  const groups: Array<{ kind: 'tool-group'; tools: ToolEntry[] }> = []
  let toolGroup: ToolEntry[] = []
  let pendingTool: { toolName: string; args?: any } | null = null

  const flushToolGroup = () => {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
      pendingTool = null
    }
    if (toolGroup.length > 0) {
      groups.push({ kind: 'tool-group', tools: [...toolGroup] })
      toolGroup = []
    }
  }

  for (const ev of events) {
    if (ev.type === 'thinking') {
      // thinking is part of the tool cycle, skip display
    } else if (ev.type === 'tool_call') {
      if (pendingTool) {
        toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
      }
      pendingTool = { toolName: ev.tool_name ?? '?', args: ev.args }
    } else if (ev.type === 'tool_result') {
      const resultContent = typeof ev.content === 'string' ? ev.content : JSON.stringify(ev.content)
      if (pendingTool) {
        toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args, result: resultContent })
        pendingTool = null
      } else {
        toolGroup.push({ toolName: ev.tool_name ?? '?', result: resultContent })
      }
    }
  }
  flushToolGroup()
  return groups
}

function ToolGroupBlock({ tools }: { tools: ToolEntry[] }) {
  const [open, setOpen] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const names = [...new Set(tools.map(t => t.toolName).filter(Boolean))]
  const summary = `${tools.length} tool calls` + (names.length > 0 ? ` — ${names.join(', ')}` : '')

  return (
    <div className="log-collapsible">
      <div className="log-collapsible-head" onClick={() => setOpen(o => !o)}>
        <span className="log-chevron">{open ? '▾' : '▸'}</span>
        <span className="log-label log-label-tool">{summary}</span>
      </div>
      {open && (
        <div className="log-collapsible-body log-tool-group-body">
          {tools.map((t, i) => {
            const isExpanded = expandedIdx === i
            const argsStr = t.args
              ? (typeof t.args === 'string' ? t.args : JSON.stringify(t.args, null, 2))
              : null
            return (
              <div key={i} className="log-tool-item">
                <div
                  className="log-tool-item-head"
                  onClick={() => setExpandedIdx(isExpanded ? null : i)}
                >
                  <span className="log-chevron">{isExpanded ? '▾' : '▸'}</span>
                  <span className="log-tool-item-name">{t.toolName || '?'}</span>
                </div>
                {isExpanded && (
                  <div className="log-tool-item-detail">
                    {argsStr && <code className="log-tool-args">{argsStr}</code>}
                    {t.result && <div className="log-tool-result">{t.result}</div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function ChatPanel({ messages, onSend, streaming = false, title, disabled = false, style }: ChatPanelProps) {
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
          const toolGroups = msg.role === 'ai' ? groupEvents(msg.events || []) : []
          return (
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
