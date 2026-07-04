/** B3 — Sync State (`sync_state`). Verdict ALIGNÉ / DIVERGENT / PARTIEL calculé côté
 *  backend partagé (CLAUDE §9) — forme + couleur, jamais couleur seule. */
import { GitMerge, GitPullRequestDraft, GitBranchPlus } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { useTerminal } from '@/store/terminal'
import { cn } from '@/lib/utils'

const SPEC = {
  ALIGNED: { label: 'ALIGNÉ', icon: GitMerge, cls: 'text-risk-green border-risk-green/60' },
  DIVERGENT: { label: 'DIVERGENT', icon: GitBranchPlus, cls: 'text-risk-red border-risk-red/60' },
  PARTIAL: { label: 'PARTIEL', icon: GitPullRequestDraft, cls: 'text-risk-yellow border-risk-yellow/60' },
} as const

export function SyncPanel() {
  const sync = useTerminal((s) => s.sync_state)
  const spec = sync ? SPEC[sync.verdict] : null
  const Icon = spec?.icon ?? GitPullRequestDraft
  return (
    <Panel code="B3" title="Sync S1 ↔ S2" block="sync_state">
      <div className={cn('flex items-center justify-center gap-2 border px-2 py-2 text-base font-black tracking-widest',
        spec?.cls ?? 'text-term-dim border-term-border')}>
        <Icon size={16} aria-hidden />
        {spec?.label ?? '—'}
      </div>
      {sync?.detail && <p className="mt-1 text-center text-xxs text-term-dim">{sync.detail}</p>}
    </Panel>
  )
}
