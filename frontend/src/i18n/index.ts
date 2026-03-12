import en from './en'
import zh from './zh'
import type { TranslationKey } from './en'

export type Locale = 'en' | 'zh'

const dictionaries: Record<Locale, Record<TranslationKey, string>> = { en, zh }

export function getTranslation(locale: Locale, key: TranslationKey): string {
  return dictionaries[locale]?.[key] ?? dictionaries.en[key] ?? key
}

export type { TranslationKey }
