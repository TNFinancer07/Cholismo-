/** Client REST — toutes les barrières (Phase 0, C5, fenêtre C3) sont re-vérifiées côté
 *  serveur ; l'UI ne fait que refléter et demander. Aucun endpoint ne passe d'ordre. */

export const API_BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return body as T
}

export const api = {
  state: () => request<unknown>('/state'),
  decisions: () => request<{ decisions: unknown[]; streak: number }>('/decisions'),
  postDecision: (operator: string, decision: 'GO' | 'NO_GO', reason?: string) =>
    request('/decisions', { method: 'POST', body: JSON.stringify({ operator, decision, reason }) }),
  armDecision: (operator: string, instrument: string) =>
    request('/decisions/arm', { method: 'POST', body: JSON.stringify({ operator, instrument }) }),
  postOutcome: (payload: { decision_id: string; outcome: string; error_type?: string | null; r_multiple?: number | null }) =>
    request('/outcomes', { method: 'POST', body: JSON.stringify(payload) }),
  postSelfcheck: (operator: string, answers: Record<string, boolean>) =>
    request('/selfcheck', { method: 'POST', body: JSON.stringify({ operator, answers }) }),
  getSelfcheck: (operator: string) =>
    request<{ present: boolean }>(`/selfcheck/${operator}`),
  ackAudit: (operator: string) =>
    request('/streak/audit-ack', { method: 'POST', body: JSON.stringify({ operator }) }),
  calibration: () => request<unknown>('/calibration'),
  orchestrator: () => request<unknown>('/orchestrator'),
  scenario: () => request<unknown>('/scenario'),
  setScenario: (payload: unknown) =>
    request('/scenario', { method: 'POST', body: JSON.stringify(payload) }),
  sources: () => request<Record<string, { up: boolean; fields: string[] }>>('/sources'),
  toggleSource: (name: string, up: boolean) =>
    request(`/sources/${name}/toggle`, { method: 'POST', body: JSON.stringify({ up }) }),
  setMode: (mode: string) => request('/mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  journal: () => request<unknown>('/journal'),
  journalCreateDraft: (strategy_id: string, operator: string) =>
    request('/journal/draft', { method: 'POST', body: JSON.stringify({ strategy_id, operator }) }),
  journalUpdateDraft: (draftId: string, fields: Record<string, unknown>) =>
    request(`/journal/draft/${draftId}`, { method: 'PUT', body: JSON.stringify({ fields }) }),
  journalDeleteDraft: (draftId: string) =>
    request(`/journal/draft/${draftId}`, { method: 'DELETE' }),
  journalLockDraft: (draftId: string) =>
    request(`/journal/draft/${draftId}/lock`, { method: 'POST' }),
  journalSentiment: (payload: unknown) =>
    request('/journal/sentiment', { method: 'POST', body: JSON.stringify(payload) }),
  journalCloseSession: () => request('/journal/close-session', { method: 'POST' }),
  journalSetN8n: (payload: unknown) =>
    request('/journal/n8n', { method: 'POST', body: JSON.stringify(payload) }),
  recap: (granularity: string) => request<unknown>(`/recap?granularity=${granularity}`),
  settings: () => request<unknown>('/settings'),
  settingsHistory: () => request<{ history: unknown[] }>('/settings/history'),
  settingsExport: () => request<unknown>('/settings/export'),
  putSetting: (key: string, payload: unknown) =>
    request(`/settings/${key}`, { method: 'PUT', body: JSON.stringify(payload) }),
  revertSetting: (key: string, payload: unknown) =>
    request(`/settings/${key}/revert`, { method: 'POST', body: JSON.stringify(payload) }),
  savePreset: (name: string) =>
    request('/settings/presets', { method: 'POST', body: JSON.stringify({ name }) }),
  applyPreset: (name: string, unlockLive: boolean) =>
    request('/settings/presets/apply', {
      method: 'POST', body: JSON.stringify({ name, unlock_live: unlockLive }) }),
  importSettings: (payload: unknown, unlockLive: boolean) =>
    request('/settings/import', {
      method: 'POST', body: JSON.stringify({ payload, unlock_live: unlockLive }) }),
  snapshotsList: () => request<unknown>('/snapshots/list'),
  snapshot: (id: string) => request<unknown>(`/snapshots/${encodeURIComponent(id)}`),
  captureSnapshot: () => request<unknown>('/snapshot', { method: 'POST' }),
  liveContext: () => request<unknown>('/live/context'),
  liveAsk: (question: string, operator: string) =>
    request<unknown>('/live/ask', { method: 'POST', body: JSON.stringify({ question, operator }) }),
  reconImport: async (file: File, tzOffsetMinutes: number) => {
    const form = new FormData()
    form.append('file', file)
    form.append('tz_offset_minutes', String(tzOffsetMinutes))
    const res = await fetch(API_BASE + '/recon/import', { method: 'POST', body: form })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
    return body
  },
}
