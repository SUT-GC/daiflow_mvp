import { Component, ErrorInfo, ReactNode } from 'react'
import { getTranslation, type Locale } from '../../i18n'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Stage-level error boundary for devflow pages.
 *
 * Unlike the global ErrorBoundary, this preserves the Shell/navigation
 * and provides a "Return to Tasks" button for recovery.
 */
export default class StageErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('StageErrorBoundary caught:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      const locale = (localStorage.getItem('daiflow-locale') as Locale) || 'en'
      return (
        <div style={{
          padding: '60px 40px',
          textAlign: 'center',
          color: 'var(--t2)',
        }}>
          <div style={{ fontSize: '24px', marginBottom: '12px' }}>
            {getTranslation(locale, 'error.title')}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--t3)', marginBottom: '20px' }}>
            {this.state.error?.message}
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
            <button
              className="btn btn-ghost"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              {getTranslation(locale, 'error.try_again')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => { window.location.href = '/tasks' }}
            >
              {getTranslation(locale, 'error.back_to_tasks')}
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
