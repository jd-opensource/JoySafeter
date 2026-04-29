'use client'

import { Suspense } from 'react'
import { ObservationViewPrefsProvider } from '../contexts/ObservationViewPrefsContext'
import { ObservationDataProvider } from '../contexts/ObservationDataContext'
import { ObservationSelectionProvider } from '../contexts/ObservationSelectionContext'
import { ObservationJsonExpansionProvider } from '../contexts/ObservationJsonExpansionContext'
import { StreamingTextProvider } from '../contexts/StreamingTextContext'

export function ObservationProviders({ children }: { children: React.ReactNode }) {
  return (
    <ObservationViewPrefsProvider>
      <ObservationDataProvider>
        <StreamingTextProvider>
          <Suspense fallback={null}>
            <ObservationSelectionProvider>
              <ObservationJsonExpansionProvider>
                {children}
              </ObservationJsonExpansionProvider>
            </ObservationSelectionProvider>
          </Suspense>
        </StreamingTextProvider>
      </ObservationDataProvider>
    </ObservationViewPrefsProvider>
  )
}
