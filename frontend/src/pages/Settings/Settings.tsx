import { useState, useEffect } from 'react'
import Topbar from '../../components/Shell/Topbar'
import { getSettings, updateSettings } from '../../api'
import { useTheme } from '../../hooks/useTheme'
import { useLocale } from '../../hooks/useLocale'
import { useSettingsContext } from '../../App'
import type { Locale } from '../../i18n'
import './Settings.css'

export default function Settings() {
  const { theme, toggleTheme } = useTheme()
  const { locale, setLocale, t } = useLocale()
  const { recheck } = useSettingsContext()
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiKeyChanged, setApiKeyChanged] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getSettings().then(data => {
      setModel(data.cody_model || '')
      setBaseUrl(data.cody_base_url || '')
      // API key comes back masked, show the masked value
      setApiKey(data.cody_api_key || '')
      setApiKeyChanged(false)
      // Sync locale from server if available
      if (data.language && (data.language === 'en' || data.language === 'zh')) {
        setLocale(data.language as Locale)
      }
    }).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const data: Record<string, string> = {
        cody_model: model,
        cody_base_url: baseUrl,
        theme,
        language: locale,
      }
      // Only send API key if user actually changed it
      if (apiKeyChanged) {
        data.cody_api_key = apiKey
      }
      await updateSettings(data)
      setMessage(t('settings.saved'))
      setApiKeyChanged(false)
      recheck()
    } catch (err: any) {
      setMessage(`Error: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleLocaleChange = (newLocale: Locale) => {
    setLocale(newLocale)
    // Also persist to backend
    updateSettings({ language: newLocale }).catch(() => {})
  }

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
                onChange={e => setModel(e.target.value)}
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
                onChange={e => setBaseUrl(e.target.value)}
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
                onChange={e => { setApiKey(e.target.value); setApiKeyChanged(true) }}
              />
            </div>
            <div className="actions">
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? t('settings.saving') : t('settings.save')}
              </button>
            </div>
            {message && (
              <p style={{ marginTop: 12, fontSize: 12, color: message.startsWith('Error') ? 'var(--red)' : 'var(--green)' }}>
                {message}
              </p>
            )}
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
