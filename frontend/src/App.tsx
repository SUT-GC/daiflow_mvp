import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import Shell from './components/Shell/Shell'
import Settings from './pages/Settings/Settings'
import Projects from './pages/Projects/Projects'
import CreateProject from './pages/Projects/CreateProject'
import EditProject from './pages/Projects/EditProject'
import ProjectInit from './pages/Projects/ProjectInit'
import ProjectKnowledge from './pages/Projects/ProjectKnowledge'
import Tasks from './pages/Tasks/Tasks'
import InitStage from './pages/DevFlow/InitStage/InitStage'
import PlanStage from './pages/DevFlow/PlanStage/PlanStage'
import TodoStage from './pages/DevFlow/TodoStage/TodoStage'
import CodingStage from './pages/DevFlow/CodingStage/CodingStage'
import ReviewStage from './pages/DevFlow/ReviewStage/ReviewStage'
import Debug from './pages/Debug/Debug'
import DevFlowGuard from './components/DevFlowGuard/DevFlowGuard'
import StageErrorBoundary from './components/StageErrorBoundary/StageErrorBoundary'
import { checkSettings } from './api'
import ErrorBoundary from './components/ErrorBoundary/ErrorBoundary'
import { ThemeContext, useThemeProvider } from './hooks/useTheme'
import { LocaleContext, useLocaleProvider } from './hooks/useLocale'
import { useWebSocket } from './ws'
import { ToastProvider } from './components/Toast/ToastContext'

// Cache settings check result to avoid repeated API calls
const SettingsContext = createContext<{ configured: boolean; model: string; recheck: () => void }>({
  configured: false,
  model: '',
  recheck: () => {},
})
export const useSettingsContext = () => useContext(SettingsContext)

function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(true)
  const [configured, setConfigured] = useState(false)
  const [model, setModel] = useState('')

  const recheck = useCallback(() => {
    checkSettings()
      .then(data => {
        setConfigured(data.configured)
        setModel(data.model || '')
      })
      .catch(() => setConfigured(false))
      .finally(() => setChecking(false))
  }, [])

  useEffect(() => { recheck() }, [recheck])

  const value = useMemo(() => ({ configured, model, recheck }), [configured, model, recheck])

  if (checking) return null
  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  )
}

function SettingsGuard({ children }: { children: React.ReactNode }) {
  const { configured } = useSettingsContext()
  if (!configured) return <Navigate to="/settings" replace />
  return <>{children}</>
}

export default function App() {
  const themeValue = useThemeProvider()
  const localeValue = useLocaleProvider()
  useWebSocket()

  return (
    <BrowserRouter>
      <ThemeContext.Provider value={themeValue}>
      <LocaleContext.Provider value={localeValue}>
      <ToastProvider>
      <SettingsProvider>
        <Shell>
          <ErrorBoundary>
          <Routes>
            <Route path="/settings" element={<Settings />} />
            <Route path="/projects" element={<SettingsGuard><Projects /></SettingsGuard>} />
            <Route path="/projects/new" element={<SettingsGuard><CreateProject /></SettingsGuard>} />
            <Route path="/projects/:projectId/edit" element={<SettingsGuard><EditProject /></SettingsGuard>} />
            <Route path="/projects/:projectId/init" element={<SettingsGuard><ProjectInit /></SettingsGuard>} />
            <Route path="/projects/:projectId/knowledge" element={<SettingsGuard><ProjectKnowledge /></SettingsGuard>} />
            <Route path="/tasks" element={<SettingsGuard><Tasks /></SettingsGuard>} />
            <Route path="/devflow/:taskId/init" element={<SettingsGuard><StageErrorBoundary><DevFlowGuard stagePath="init"><InitStage /></DevFlowGuard></StageErrorBoundary></SettingsGuard>} />
            <Route path="/devflow/:taskId/plan" element={<SettingsGuard><StageErrorBoundary><DevFlowGuard stagePath="plan"><PlanStage /></DevFlowGuard></StageErrorBoundary></SettingsGuard>} />
            <Route path="/devflow/:taskId/todo" element={<SettingsGuard><StageErrorBoundary><DevFlowGuard stagePath="todo"><TodoStage /></DevFlowGuard></StageErrorBoundary></SettingsGuard>} />
            <Route path="/devflow/:taskId/coding" element={<SettingsGuard><StageErrorBoundary><DevFlowGuard stagePath="coding"><CodingStage /></DevFlowGuard></StageErrorBoundary></SettingsGuard>} />
            <Route path="/devflow/:taskId/review" element={<SettingsGuard><StageErrorBoundary><DevFlowGuard stagePath="review"><ReviewStage /></DevFlowGuard></StageErrorBoundary></SettingsGuard>} />
            <Route path="/debug" element={<SettingsGuard><Debug /></SettingsGuard>} />
            <Route path="/" element={<Navigate to="/projects" replace />} />
          </Routes>
          </ErrorBoundary>
        </Shell>
      </SettingsProvider>
      </ToastProvider>
      </LocaleContext.Provider>
      </ThemeContext.Provider>
    </BrowserRouter>
  )
}
