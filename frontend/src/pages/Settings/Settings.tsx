import { useState, useEffect } from 'react'
import Topbar from '../../components/Shell/Topbar'
import { getSettings, updateSettings, testConnection } from '../../api'
import { useTheme } from '../../hooks/useTheme'
import { useLocale } from '../../hooks/useLocale'
import { useSettingsContext } from '../../App'
import { useToast } from '../../components/Toast/ToastContext'
import type { Locale } from '../../i18n'
import './Settings.css'

// 'idle' = default, 'testing' = in progress, 'ok' = test passed, 'error' = test failed
type TestState = 'idle' | 'testing' | 'ok' | 'error'

export default function Settings() {
  const { theme, toggleTheme } = useTheme()
  const { locale, setLocale, t } = useLocale()
  const { recheck } = useSettingsContext()
  const toast = useToast()
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiKeyChanged, setApiKeyChanged] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testState, setTestState] = useState<TestState>('idle')
  const [testError, setTestError] = useState('')

  useEffect(() => {
    getSettings().then(data => {
      setModel(data.cody_model || '')
      setBaseUrl(data.cody_base_url || '')
      setApiKey(data.cody_api_key || '')
      setApiKeyChanged(false)
      if (data.language && (data.language === 'en' || data.language === 'zh')) {
        setLocale(data.language as Locale)
      }
    }).catch(() => {})
  }, [])

  // Reset test state when user edits any field
  const onFieldChange = (setter: (v: string) => void, value: string, isApiKey = false) => {
    setter(value)
    if (isApiKey) setApiKeyChanged(true)
    if (testState === 'ok' || testState === 'error') {
      setTestState('idle')
      setTestError('')
    }
  }

  const handleTest = async () => {
    setTestState('testing')
    setTestError('')
    try {
      await testConnection({ cody_model: model, cody_base_url: baseUrl, cody_api_key: apiKey })
      setTestState('ok')
    } catch (err: any) {
      setTestState('error')
      setTestError(err.message || 'Connection failed')
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const data: Record<string, string> = {
        cody_model: model,
        cody_base_url: baseUrl,
        theme,
        language: locale,
      }
      if (apiKeyChanged) {
        data.cody_api_key = apiKey
      }
      await updateSettings(data)
      toast.success(t('settings.saved'))
      setApiKeyChanged(false)
      setTestState('idle')
      recheck()
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleCancel = () => {
    setTestState('idle')
    setTestError('')
  }

  const handleLocaleChange = (newLocale: Locale) => {
    setLocale(newLocale)
    updateSettings({ language: newLocale }).catch(() => {})
  }

  const formDisabled = testState === 'testing'

  return (
    <>
      <Topbar title={t('settings.title')} />
      <div className="content">
        <div className="settings-page">
          <div className="eyebrow">{t('settings.eyebrow')}</div>
          <h1 className="page-title">{t('settings.heading')}</h1>
          <p className="page-desc">{t('settings.desc')}</p>

          <div className="card settings-card">
            <div className="field">
              <label className="field-label">
                {t('settings.model_name')} <code>cody_model</code>
              </label>
              <input
                className="input"
                placeholder="e.g. claude-sonnet-4-20250514"
                value={model}
                disabled={formDisabled}
                onChange={e => onFieldChange(setModel, e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label">
                {t('settings.api_url')} <code>cody_base_url</code>
              </label>
              <input
                className="input"
                placeholder="e.g. https://api.anthropic.com"
                value={baseUrl}
                disabled={formDisabled}
                onChange={e => onFieldChange(setBaseUrl, e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label">
                {t('settings.api_key')} <code>cody_api_key</code>
              </label>
              <input
                className="input"
                type="password"
                placeholder="sk-..."
                value={apiKey}
                disabled={formDisabled}
                onChange={e => onFieldChange(setApiKey, e.target.value, true)}
              />
            </div>

            {testState === 'ok' && (
              <div className="test-result test-ok">{t('settings.test_ok')}</div>
            )}
            {testState === 'error' && (
              <div className="test-result test-fail">{testError}</div>
            )}

            <div className="actions">
              {testState === 'ok' ? (
                <>
                  <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                    {saving ? t('settings.saving') : t('settings.save')}
                  </button>
                  <button className="btn btn-ghost" onClick={handleCancel}>
                    {t('settings.cancel')}
                  </button>
                </>
              ) : (
                <button
                  className="btn btn-primary"
                  onClick={handleTest}
                  disabled={testState === 'testing' || !model || !baseUrl || !apiKey}
                >
                  {testState === 'testing' ? t('settings.testing') : t('settings.test')}
                </button>
              )}
            </div>
          </div>

          <div className="section-head">{t('settings.appearance')}</div>
          <div className="theme-switch">
            <div
              className={`theme-option ${theme === 'dark' ? 'selected' : ''}`}
              onClick={() => { if (theme !== 'dark') toggleTheme() }}
            >
              <div className="theme-option-icon">🌙</div>
              <div className="theme-option-label">{t('settings.dark')}</div>
            </div>
            <div
              className={`theme-option ${theme === 'light' ? 'selected' : ''}`}
              onClick={() => { if (theme !== 'light') toggleTheme() }}
            >
              <div className="theme-option-icon">☀️</div>
              <div className="theme-option-label">{t('settings.light')}</div>
            </div>
          </div>

          <div className="section-head">{t('settings.language')}</div>
          <div className="theme-switch">
            <div
              className={`theme-option ${locale === 'en' ? 'selected' : ''}`}
              onClick={() => handleLocaleChange('en')}
            >
              <div className="theme-option-icon">EN</div>
              <div className="theme-option-label">{t('settings.lang_en')}</div>
            </div>
            <div
              className={`theme-option ${locale === 'zh' ? 'selected' : ''}`}
              onClick={() => handleLocaleChange('zh')}
            >
              <div className="theme-option-icon">中</div>
              <div className="theme-option-label">{t('settings.lang_zh')}</div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
