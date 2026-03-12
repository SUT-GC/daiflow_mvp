import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { getTranslation, type Locale, type TranslationKey } from '../i18n'

function getInitialLocale(): Locale {
  return (localStorage.getItem('daiflow-locale') as Locale) || 'en'
}

interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: TranslationKey) => string
}

export const LocaleContext = createContext<LocaleContextValue>({
  locale: 'en',
  setLocale: () => {},
  t: (key) => key,
})

export function useLocaleProvider() {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale)

  useEffect(() => {
    localStorage.setItem('daiflow-locale', locale)
  }, [locale])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
  }, [])

  const t = useCallback((key: TranslationKey) => {
    return getTranslation(locale, key)
  }, [locale])

  return { locale, setLocale, t }
}

export function useLocale() {
  return useContext(LocaleContext)
}
