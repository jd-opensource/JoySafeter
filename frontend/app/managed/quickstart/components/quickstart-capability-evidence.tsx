'use client'

import {
  CheckCircle2,
  CircleMinus,
  PlugZap,
  Puzzle,
  ScrollText,
  ShieldCheck,
  Wrench,
} from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import type { QuickstartCapabilityEvidence as CapabilityEvidence } from '@/lib/managed/quickstart-capabilities'

interface QuickstartCapabilityEvidenceProps {
  evidence: CapabilityEvidence
}

function EvidenceRow({
  positive,
  icon: Icon,
  children,
}: {
  positive: boolean
  icon: typeof CheckCircle2
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-background px-3 py-2 text-xs">
      <Icon
        className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${positive ? 'text-emerald-600' : 'text-muted-foreground'}`}
      />
      <span className="text-foreground/90">{children}</span>
    </div>
  )
}

export function QuickstartCapabilityEvidence({ evidence }: QuickstartCapabilityEvidenceProps) {
  const { t } = useTranslation()

  return (
    <section className="border-b border-border bg-muted/20 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <ShieldCheck className="h-4 w-4 text-primary" />
        {t('managed.quickstart.capabilityEvidence.title')}
      </div>
      <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
        {t('managed.quickstart.capabilityEvidence.description')}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <EvidenceRow positive={evidence.responseReceived} icon={CheckCircle2}>
          {t(
            evidence.responseReceived
              ? 'managed.quickstart.capabilityEvidence.responseObserved'
              : 'managed.quickstart.capabilityEvidence.responsePending',
          )}
        </EvidenceRow>
        <EvidenceRow positive={evidence.environmentAttached} icon={ShieldCheck}>
          {t(
            evidence.environmentAttached
              ? 'managed.quickstart.capabilityEvidence.environmentAttached'
              : 'managed.quickstart.capabilityEvidence.noEnvironment',
          )}
        </EvidenceRow>
        <EvidenceRow positive={evidence.externalToolsAuthorized} icon={PlugZap}>
          {t(
            evidence.externalToolsAuthorized
              ? 'managed.quickstart.capabilityEvidence.externalToolsAuthorized'
              : 'managed.quickstart.capabilityEvidence.externalToolsNotAuthorized',
          )}
        </EvidenceRow>
        <EvidenceRow positive={evidence.configuredSkills.length > 0} icon={Puzzle}>
          {evidence.configuredSkills.length
            ? `${t('managed.quickstart.capabilityEvidence.skillsConfigured')}: ${evidence.configuredSkills.join(', ')}`
            : t('managed.quickstart.capabilityEvidence.noSkillsConfigured')}
        </EvidenceRow>
        <EvidenceRow positive={evidence.observedTools.length > 0} icon={Wrench}>
          {evidence.observedTools.length
            ? `${t('managed.quickstart.capabilityEvidence.toolsObserved')}: ${evidence.observedTools.join(', ')}`
            : t('managed.quickstart.capabilityEvidence.noToolCalls')}
        </EvidenceRow>
        <EvidenceRow positive={evidence.observedMcpTools.length > 0} icon={PlugZap}>
          {evidence.observedMcpTools.length
            ? `${t('managed.quickstart.capabilityEvidence.mcpObserved')}: ${evidence.observedMcpTools.join(', ')}`
            : t('managed.quickstart.capabilityEvidence.noMcpCalls')}
        </EvidenceRow>
        <EvidenceRow
          positive={evidence.auditEventsAvailable}
          icon={evidence.auditEventsAvailable ? ScrollText : CircleMinus}
        >
          {t(
            evidence.auditEventsAvailable
              ? 'managed.quickstart.capabilityEvidence.auditAvailable'
              : 'managed.quickstart.capabilityEvidence.auditPending',
          )}
        </EvidenceRow>
      </div>
    </section>
  )
}
