import { createContext, useCallback, useContext, useState } from 'react'
import { createPortal } from 'react-dom'
import './Toast.css'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastItem {
  id: number
  type: ToastType
  message: string
}

interface ToastContextValue {
  success: (message: string) => void
  error: (message: string) => void
  warning: (message: string) => void
  info: (message: string) => void
}

const ToastContext = createContext<ToastContextValue>({
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
})

export const useToast = () => useContext(ToastContext)

let nextId = 0

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const add = useCallback((type: ToastType, message: string) => {
    const id = nextId++
    setToasts(prev => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, type === 'error' ? 5000 : 3000)
  }, [])

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const value: ToastContextValue = {
    success: useCallback((msg: string) => add('success', msg), [add]),
    error: useCallback((msg: string) => add('error', msg), [add]),
    warning: useCallback((msg: string) => add('warning', msg), [add]),
    info: useCallback((msg: string) => add('info', msg), [add]),
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="toast-container">
          {toasts.map(t => (
            <div key={t.id} className={`toast toast-${t.type}`} onClick={() => dismiss(t.id)}>
              <span className="toast-icon">
                {t.type === 'success' ? '✓' : t.type === 'error' ? '✗' : t.type === 'warning' ? '!' : 'i'}
              </span>
              <span className="toast-message">{t.message}</span>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}
