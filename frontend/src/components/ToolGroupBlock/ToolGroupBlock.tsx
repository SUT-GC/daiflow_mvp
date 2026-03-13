import { useState } from 'react'
import type { ToolEntry } from '../../utils/groupToolEvents'

export default function ToolGroupBlock({ tools }: { tools: ToolEntry[] }) {
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
