import { useState, useRef, useCallback, useEffect, cloneElement, isValidElement } from 'react'

/** Minimum width before the right panel snaps to collapsed */
const COLLAPSE_THRESHOLD = 60

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
  const [collapsed, setCollapsed] = useState(false)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(initialRightWidth)
  const prevWidth = useRef(initialRightWidth)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = collapsed ? 0 : rightWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [rightWidth, collapsed])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const delta = startX.current - e.clientX
      const raw = startWidth.current + delta

      if (raw < COLLAPSE_THRESHOLD) {
        setCollapsed(true)
        setRightWidth(0)
      } else {
        setCollapsed(false)
        const newWidth = Math.max(minRightWidth, Math.min(maxRightWidth, raw))
        setRightWidth(newWidth)
        prevWidth.current = newWidth
      }
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

  // Double-click to toggle collapse
  const onDoubleClick = useCallback(() => {
    if (collapsed) {
      setCollapsed(false)
      setRightWidth(prevWidth.current || initialRightWidth)
    } else {
      prevWidth.current = rightWidth
      setCollapsed(true)
      setRightWidth(0)
    }
  }, [collapsed, rightWidth, initialRightWidth])

  // Inject width style into the right panel element
  const rightPanel = isValidElement(right)
    ? cloneElement(right, {
        style: {
          ...right.props.style,
          width: collapsed ? 0 : rightWidth,
          overflow: collapsed ? 'hidden' : undefined,
          display: collapsed ? 'none' : undefined,
        },
      })
    : right

  return (
    <>
      <div className="devflow-main">
        {children}
      </div>
      <div className="resize-handle" onMouseDown={onMouseDown} onDoubleClick={onDoubleClick} />
      {rightPanel}
    </>
  )
}
