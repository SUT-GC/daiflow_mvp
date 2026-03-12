import { Fragment, memo, useMemo, useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useTheme } from '../../hooks/useTheme'
import './DiffViewer.css'

interface DiffFile {
  path: string
  additions: number
  deletions: number
  hunks: DiffHunk[]
  binary?: boolean
  language?: string
}

interface DiffHunk {
  header: string
  lines: DiffLine[]
}

interface DiffLine {
  type: 'add' | 'remove' | 'context' | 'hunk'
  content: string
  oldNum?: number
  newNum?: number
}

type DiffViewMode = 'unified' | 'split'

interface DiffViewerProps {
  diffs: string  // raw git diff
  collapsed?: Record<string, boolean>
  onToggleFile?: (path: string) => void
  defaultMode?: DiffViewMode
}

const EXT_TO_LANG: Record<string, string> = {
  ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
  py: 'python', rs: 'rust', go: 'go', java: 'java',
  rb: 'ruby', php: 'php', css: 'css', scss: 'scss',
  html: 'html', json: 'json', yaml: 'yaml', yml: 'yaml',
  md: 'markdown', sql: 'sql', sh: 'bash', bash: 'bash',
  c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp',
  swift: 'swift', kt: 'kotlin', toml: 'toml', xml: 'xml',
}

function detectLanguage(path: string): string | undefined {
  const ext = path.split('.').pop()?.toLowerCase()
  return ext ? EXT_TO_LANG[ext] : undefined
}

export function parseDiff(raw: string): DiffFile[] {
  const files: DiffFile[] = []
  const fileChunks = raw.split(/^diff --git /m).filter(Boolean)

  for (const chunk of fileChunks) {
    const lines = chunk.split('\n')
    const headerMatch = lines[0]?.match(/a\/(.+?) b\/(.+)/)
    const path = headerMatch ? headerMatch[2] : 'unknown'

    // Check for binary files
    if (chunk.includes('Binary files') || chunk.includes('GIT binary patch')) {
      files.push({ path, additions: 0, deletions: 0, hunks: [], binary: true })
      continue
    }

    let additions = 0
    let deletions = 0
    const hunks: DiffHunk[] = []
    let currentHunk: DiffHunk | null = null
    let oldNum = 0
    let newNum = 0

    for (const line of lines.slice(1)) {
      if (line.startsWith('@@')) {
        const match = line.match(/@@ -(\d+),?\d* \+(\d+),?\d* @@(.*)/)
        if (match) {
          oldNum = parseInt(match[1]) - 1
          newNum = parseInt(match[2]) - 1
          currentHunk = { header: line, lines: [] }
          hunks.push(currentHunk)
        }
      } else if (currentHunk) {
        if (line.startsWith('+')) {
          newNum++
          additions++
          currentHunk.lines.push({ type: 'add', content: line.slice(1), newNum })
        } else if (line.startsWith('-')) {
          oldNum++
          deletions++
          currentHunk.lines.push({ type: 'remove', content: line.slice(1), oldNum })
        } else if (line.startsWith(' ') || line === '') {
          oldNum++
          newNum++
          currentHunk.lines.push({ type: 'context', content: line.slice(1), oldNum, newNum })
        }
      }
    }

    if (hunks.length > 0) {
      files.push({ path, additions, deletions, hunks, binary: false, language: detectLanguage(path) })
    }
  }

  return files
}

const HighlightedCode = memo(function HighlightedCode({ code, language, highlightStyle }: { code: string; language?: string; highlightStyle: any }) {
  if (!language) {
    return <>{code}</>
  }
  return (
    <SyntaxHighlighter
      language={language}
      style={highlightStyle}
      customStyle={{
        display: 'inline',
        background: 'transparent',
        padding: 0,
        margin: 0,
        fontSize: 'inherit',
        fontFamily: 'inherit',
        lineHeight: 'inherit',
        whiteSpace: 'pre',
      }}
      codeTagProps={{ style: { background: 'transparent' } }}
      PreTag="span"
    >
      {code}
    </SyntaxHighlighter>
  )
})

interface SplitRow {
  left: DiffLine | null
  right: DiffLine | null
}

function buildSplitRows(hunk: DiffHunk): SplitRow[] {
  const rows: SplitRow[] = []
  const lines = hunk.lines
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (line.type === 'context') {
      rows.push({ left: line, right: line })
      i++
    } else if (line.type === 'remove') {
      // Collect consecutive removes
      const removes: DiffLine[] = []
      while (i < lines.length && lines[i].type === 'remove') {
        removes.push(lines[i])
        i++
      }
      // Collect consecutive adds that follow
      const adds: DiffLine[] = []
      while (i < lines.length && lines[i].type === 'add') {
        adds.push(lines[i])
        i++
      }
      // Pair them up
      const max = Math.max(removes.length, adds.length)
      for (let j = 0; j < max; j++) {
        rows.push({
          left: j < removes.length ? removes[j] : null,
          right: j < adds.length ? adds[j] : null,
        })
      }
    } else if (line.type === 'add') {
      rows.push({ left: null, right: line })
      i++
    } else {
      i++
    }
  }
  return rows
}

function UnifiedDiffBody({ file, highlightStyle }: { file: DiffFile; highlightStyle: any }) {
  return (
    <table className="diff-table">
      <tbody>
        {file.hunks.map((hunk, hi) => (
          <Fragment key={hi}>
            <tr className="hunk">
              <td className="ln" />
              <td className="ln2" />
              <td className="code">{hunk.header}</td>
            </tr>
            {hunk.lines.map((line, li) => (
              <tr key={li} className={line.type === 'add' ? 'add' : line.type === 'remove' ? 'rm' : 'ctx'}>
                <td className="ln">{line.type !== 'add' ? line.oldNum : ''}</td>
                <td className="ln2">{line.type !== 'remove' ? line.newNum : ''}</td>
                <td className="code">
                  {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
                  <HighlightedCode code={line.content} language={file.language} highlightStyle={highlightStyle} />
                </td>
              </tr>
            ))}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

function SplitDiffBody({ file, highlightStyle }: { file: DiffFile; highlightStyle: any }) {
  return (
    <table className="diff-table diff-table-split">
      <tbody>
        {file.hunks.map((hunk, hi) => {
          const splitRows = buildSplitRows(hunk)
          return (
            <Fragment key={hi}>
              <tr className="hunk">
                <td className="ln" />
                <td className="code split-left">{hunk.header}</td>
                <td className="ln" />
                <td className="code split-right">{hunk.header}</td>
              </tr>
              {splitRows.map((row, ri) => (
                <tr key={ri}>
                  <td className={`ln ${row.left?.type === 'remove' ? 'rm' : ''}`}>
                    {row.left?.oldNum ?? ''}
                  </td>
                  <td className={`code split-left ${row.left?.type === 'remove' ? 'rm' : row.left?.type === 'context' ? 'ctx' : 'empty'}`}>
                    {row.left ? (
                      <>
                        {row.left.type === 'remove' ? '-' : ' '}
                        <HighlightedCode code={row.left.content} language={file.language} highlightStyle={highlightStyle} />
                      </>
                    ) : ''}
                  </td>
                  <td className={`ln ${row.right?.type === 'add' ? 'add' : ''}`}>
                    {row.right?.newNum ?? ''}
                  </td>
                  <td className={`code split-right ${row.right?.type === 'add' ? 'add' : row.right?.type === 'context' ? 'ctx' : 'empty'}`}>
                    {row.right ? (
                      <>
                        {row.right.type === 'add' ? '+' : ' '}
                        <HighlightedCode code={row.right.content} language={file.language} highlightStyle={highlightStyle} />
                      </>
                    ) : ''}
                  </td>
                </tr>
              ))}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

export default function DiffViewer({ diffs, collapsed = {}, onToggleFile, defaultMode = 'unified' }: DiffViewerProps) {
  const [viewMode, setViewMode] = useState<DiffViewMode>(defaultMode)
  const { theme } = useTheme()
  const highlightStyle = theme === 'dark' ? oneDark : oneLight
  const files = useMemo(() => parseDiff(diffs), [diffs])

  if (files.length === 0) {
    return <div style={{ color: 'var(--t2)', padding: '20px', textAlign: 'center' }}>No changes</div>
  }

  return (
    <div className="diff-viewer">
      <div className="diff-mode-toggle">
        <button
          className={`diff-mode-btn ${viewMode === 'unified' ? 'active' : ''}`}
          onClick={() => setViewMode('unified')}
        >
          Unified
        </button>
        <button
          className={`diff-mode-btn ${viewMode === 'split' ? 'active' : ''}`}
          onClick={() => setViewMode('split')}
        >
          Split
        </button>
      </div>
      {files.map(file => {
        const isCollapsed = collapsed[file.path] ?? false
        return (
          <div key={file.path} className={`diff-file-block ${isCollapsed ? 'collapsed' : ''}`}>
            <div
              className="diff-file-header"
              onClick={() => onToggleFile?.(file.path)}
            >
              <span className="collapse-icon">{isCollapsed ? '›' : '⌄'}</span>
              <span className="diff-file-path">{file.path}</span>
              <span className="diff-file-stats">
                <span style={{ color: 'var(--green)' }}>+{file.additions}</span>
                {' '}
                <span style={{ color: 'var(--red)' }}>-{file.deletions}</span>
              </span>
            </div>
            {file.binary ? (
              <div className="diff-body" style={{ padding: '12px 16px', color: 'var(--t3)', fontStyle: 'italic' }}>
                Binary file
              </div>
            ) : !isCollapsed && (
              <div className="diff-body">
                {viewMode === 'split'
                  ? <SplitDiffBody file={file} highlightStyle={highlightStyle} />
                  : <UnifiedDiffBody file={file} highlightStyle={highlightStyle} />
                }
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
