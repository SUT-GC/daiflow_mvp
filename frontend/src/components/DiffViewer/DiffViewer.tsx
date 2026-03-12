import { Fragment, memo, useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
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

interface DiffViewerProps {
  diffs: string  // raw git diff
  collapsed?: Record<string, boolean>
  onToggleFile?: (path: string) => void
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

function parseDiff(raw: string): DiffFile[] {
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

const HighlightedCode = memo(function HighlightedCode({ code, language }: { code: string; language?: string }) {
  if (!language) {
    return <>{code}</>
  }
  return (
    <SyntaxHighlighter
      language={language}
      style={oneDark}
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

export default function DiffViewer({ diffs, collapsed = {}, onToggleFile }: DiffViewerProps) {
  const files = useMemo(() => parseDiff(diffs), [diffs])

  if (files.length === 0) {
    return <div style={{ color: 'var(--t2)', padding: '20px', textAlign: 'center' }}>No changes</div>
  }

  return (
    <div className="diff-viewer">
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
                              <HighlightedCode code={line.content} language={file.language} />
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
