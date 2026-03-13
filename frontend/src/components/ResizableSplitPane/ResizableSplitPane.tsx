import { useState, useRef, useCallback, useEffect, cloneElement, isValidElement } from 'react'

interface ResizableSplitPaneProps {
  /** Left/main content */
  children: React.ReactNode
  /** Right panel element (e.g. ChatPanel) — receives style={{ width }} */
  right: React.ReactElement<{ style?: React.CSSProperties }>
  /** Initial width of the right panel in px (default 340) */
  initialRightWidth?: number
  /** Min width of the right panel in px (default 240) */
  minRightWidth?: number
  /** Max width of the right panel in px (default 800) */
  maxRightWidth?: number
}

export default function ResizableSplitPane({
  children,
  right,
  initialRightWidth = 340,
  minRightWidth = 240,
  maxRightWidth = 800,
}: ResizableSplitPaneProps) {
  const [rightWidth, setRightWidth] = useState(initialRightWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(initialRightWidth)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = rightWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [rightWidth])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const delta = startX.current - e.clientX
      const newWidth = Math.max(minRightWidth, Math.min(maxRightWidth, startWidth.current + delta))
      setRightWidth(newWidth)
    }
    const onMouseUp = () => {
      if (dragging.current) {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [minRightWidth, maxRightWidth])

  // Inject width style into the right panel element
  const rightPanel = isValidElement(right)
    ? cloneElement(right, { style: { ...right.props.style, width: rightWidth } })
    : right

  return (
    <div className="devflow-body">
      <div className="devflow-main">
        {children}
      </div>
      <div className="resize-handle" onMouseDown={onMouseDown} />
      {rightPanel}
    </div>
  )
}
