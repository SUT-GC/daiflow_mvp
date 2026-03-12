import { Component, ErrorInfo, ReactNode } from 'react'
import { getTranslation, type Locale } from '../../i18n'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      const locale = (localStorage.getItem('daiflow-locale') as Locale) || 'en'
      return (
        <div style={{
          padding: '40px',
          textAlign: 'center',
          color: 'var(--t2)',
        }}>
          <div style={{ fontSize: '24px', marginBottom: '12px' }}>{getTranslation(locale, 'error.title')}</div>
          <div style={{ fontSize: '13px', color: 'var(--t3)', marginBottom: '20px' }}>
            {this.state.error?.message}
          </div>
          <button
            className="btn btn-ghost"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            {getTranslation(locale, 'error.try_again')}
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
