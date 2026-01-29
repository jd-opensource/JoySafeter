'use client'

import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import en from './locales/en'
import zh from './locales/zh'

// Initialize i18n only on the client side
if (typeof window !== 'undefined' && !i18n.isInitialized) {
  i18n
    .use(LanguageDetector)
    .use(initReactI18next) 
    .init({
      resources: {
        en: {
          translation: en.translation,
        },
        zh: {
          translation: zh.translation,
        },
      },
      defaultNS: 'translation',
      fallbackLng: 'en', 
      interpolation: {
        escapeValue: false, 
      },
      detection: {
        order: ['localStorage', 'cookie', 'navigator'], 
        caches: ['localStorage', 'cookie'], 
        lookupLocalStorage: 'i18nextLng', 
        lookupCookie: 'i18next', 
      },
    })
}

export default i18n
