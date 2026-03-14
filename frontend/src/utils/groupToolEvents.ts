/**
 * Shared utility for grouping consecutive tool_call/tool_result/thinking events
 * into collapsible tool-group blocks.
 *
 * Used by both ChatPanel (chat messages) and ProjectInit (session logs).
 */

export type ToolEntry = { toolName: string; args?: Record<string, unknown>; result?: string }

/**
 * Flush pending tool state into groups.
 * Core logic shared between groupChatToolEvents and groupLogBlocks.
 */
function processTool(
  event: { type: string; tool_name?: string; args?: Record<string, unknown>; content?: string },
  pendingTool: { toolName: string; args?: Record<string, unknown> } | null,
  toolGroup: ToolEntry[],
): { pendingTool: typeof pendingTool } {
  if (event.type === 'tool_call') {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
    }
    return { pendingTool: { toolName: event.tool_name ?? '?', args: event.args } }
  }
  if (event.type === 'tool_result') {
    const resultContent = event.content ?? ''
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args, result: resultContent })
    } else {
      toolGroup.push({ toolName: event.tool_name ?? '?', result: resultContent })
    }
    return { pendingTool: null }
  }
  return { pendingTool }
}

/**
 * Group chat message events (thinking/tool_call/tool_result) into tool groups.
 * Used by ChatPanel for individual AI messages.
 */
export function groupChatToolEvents(events: Array<{ type: string; tool_name?: string; args?: Record<string, unknown>; content?: string }>): Array<{ kind: 'tool-group'; tools: ToolEntry[] }> {
  if (!events || events.length === 0) return []
  const groups: Array<{ kind: 'tool-group'; tools: ToolEntry[] }> = []
  let toolGroup: ToolEntry[] = []
  let pendingTool: { toolName: string; args?: Record<string, unknown> } | null = null

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
    } else if (ev.type === 'tool_call' || ev.type === 'tool_result') {
      const result = processTool(ev, pendingTool, toolGroup)
      pendingTool = result.pendingTool
    }
  }
  flushToolGroup()
  return groups
}

export type LogBlock =
  | { kind: 'text'; content: string }
  | { kind: 'tool-group'; tools: ToolEntry[] }
  | { kind: 'error'; content: string }
  | { kind: 'status'; status: number }

/**
 * Group session log events into display blocks (text, tool-groups, errors, status).
 * Used by ProjectInit for session log modals.
 */
export function groupLogBlocks(logs: Array<{ type: string; content?: string; tool_name?: string; args?: Record<string, unknown>; error?: string; status?: number }>): LogBlock[] {
  const blocks: LogBlock[] = []
  let textBuf = ''
  let toolGroup: ToolEntry[] = []
  let pendingTool: { toolName: string; args?: Record<string, unknown> } | null = null

  const flushText = () => {
    if (textBuf) { blocks.push({ kind: 'text', content: textBuf }); textBuf = '' }
  }
  const flushToolGroup = () => {
    if (pendingTool) {
      toolGroup.push({ toolName: pendingTool.toolName, args: pendingTool.args })
      pendingTool = null
    }
    if (toolGroup.length > 0) {
      blocks.push({ kind: 'tool-group', tools: [...toolGroup] })
      toolGroup = []
    }
  }

  for (const log of logs) {
    if (log.type === 'text_delta') {
      flushToolGroup()
      textBuf += log.content ?? ''
    } else if (log.type === 'thinking') {
      flushText()
    } else if (log.type === 'tool_call' || log.type === 'tool_result') {
      flushText()
      const result = processTool(log, pendingTool, toolGroup)
      pendingTool = result.pendingTool
    } else if (log.type === 'error') {
      flushText(); flushToolGroup()
      blocks.push({ kind: 'error', content: log.content || log.error || '' })
    } else if (log.type === 'status_change') {
      flushText(); flushToolGroup()
      blocks.push({ kind: 'status', status: log.status ?? 0 })
    }
  }
  flushText(); flushToolGroup()
  return blocks
}
