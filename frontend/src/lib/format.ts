/** Formatage monospace dense, style terminal financier. */

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('fr-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return Math.round(v).toLocaleString('fr-CA')
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return (v > 0 ? '+' : '') + fmtNum(v, digits)
}

/** GEX en milliards lisibles. */
export function fmtGex(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return (v / 1e9).toFixed(2) + ' G$'
}

/** Âge de donnée en clair (PRD §B2 : âge réel, pas de countdown inventé). */
export function fmtAge(seconds: number | null): string {
  if (seconds === null || seconds < 0) return '—'
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m${String(Math.floor(seconds % 60)).padStart(2, '0')}`
  return `${Math.floor(seconds / 3600)}h${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}`
}

export function fmtClock(date: Date, timeZone: string): string {
  return date.toLocaleTimeString('en-GB', { timeZone, hour12: false })
}

export function fmtTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('en-GB', { hour12: false })
}
