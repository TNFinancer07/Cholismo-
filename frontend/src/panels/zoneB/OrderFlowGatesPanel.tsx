/** Gates d'order flow LSR — lit UN champ : `extras.orderflow_shadow` (CLAUDE §1).
 *
 *  DEUX panneaux, pas un (D-099). Le backend distingue déjà des gates qui portent un VERDICT
 *  (OF1/OF2) de mesures explicitement NON GATANTES (OF3/OF4, seuils non calibrés) ; les afficher
 *  ensemble laisserait croire que les quatre pèsent pareil sur la décision. L'écran garde la
 *  distinction que le calcul fait.
 *
 *  NOMENCLATURE : `OF1`-`OF4` à l'écran. Le backend les nomme `b1`-`b4`, mais `B1` est déjà le
 *  code de POSITION d'un panneau React (« B1 · États S1 · S2 ») — deux `B1` de sens différents
 *  dans la même interface seraient exactement l'ambiguïté que ce terminal refuse ailleurs.
 *
 *  LECTURE SEULE (§2.1). FAIL-CLOSED (§3) : mesure absente → « — », jamais un 0 ; verdict absent
 *  → « non mesurable », jamais « passe ». */
import { useTerminal } from '@/store/terminal'
import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/utils'
import type { OrderFlowGate, OrderFlowShadow, OrderFlowThreshold } from '@/types/schema'

const GATE_LABELS: Record<'b1' | 'b2', { code: string; label: string }> = {
  b1: { code: 'OF1', label: 'rechargement du mur' },
  b2: { code: 'OF2', label: 'bascule du tape' },
}

const MEASURE_LABELS: Record<'b3' | 'b4', { code: string; label: string }> = {
  b3: { code: 'OF3', label: 'CVD normalisé' },
  b4: { code: 'OF4', label: "vitesse d'agression" },
}

/** `—` couvre `null`, `undefined` et le non-fini. Un 0 affiché serait une mesure. */
export function fmtMesure(v: number | boolean | null | undefined): string {
  if (typeof v === 'boolean') return v ? 'oui' : 'non'
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return (Math.round(v * 1000) / 1000).toString()
}

/** Le verdict n'est JAMAIS encodé par la seule couleur (§3, daltonisme) : texte + icône. */
export function verdictTexte(v: boolean | null | undefined): { txt: string; icone: string; cls: string } {
  if (v === null || v === undefined) return { txt: 'non mesurable', icone: '·', cls: 'text-term-faint' }
  return v
    ? { txt: 'franchie', icone: '✓', cls: 'text-bias-up' }
    : { txt: 'refusée', icone: '✕', cls: 'text-bias-down' }
}

/** Repère de seuil. `op` est affiché AVEC la valeur : « 0.4 » seul ne dit pas de quel côté il
 *  faut être, et B2 change de sens selon la direction du sweep. Absent → « — », jamais un
 *  seuil supposé. */
export function Seuil({ t }: { t?: OrderFlowThreshold | null }) {
  if (!t || !Number.isFinite(t.value)) {
    return <span className="text-term-faint" title="instrument non calibré">—</span>
  }
  return (
    <span className={t.applied ? 'text-term-dim' : 'text-term-faint'}
      title={t.applied ? 'seuil appliqué par le moteur' : 'seuil de référence — NON appliqué'}>
      {t.op} {t.value}{t.applied ? '' : ' (réf.)'}
    </span>
  )
}

function LigneGate({ gate, code, label, seuil }: {
  gate?: OrderFlowGate; code: string; label: string; seuil?: OrderFlowThreshold | null
}) {
  const src = verdictTexte(gate?.verdict_source)
  const ih = verdictTexte(gate?.verdict_inhouse)
  // `agree` n'est vrai/faux que si les DEUX verdicts existent ; `null` = indécidable, et
  // l'afficher comme « accord » ferait passer une absence de mesure pour une confirmation.
  const accord = gate?.agree
  return (
    <tr className="border-t border-term-border/50">
      <td className="py-0.5 pr-2 font-bold text-term-text">{code}</td>
      <td className="py-0.5 pr-2 text-term-dim">{label}</td>
      <td className={cn('py-0.5 pr-2 tabular-nums', src.cls)} title={`proxy fournisseur : ${src.txt}`}>
        <span aria-hidden>{src.icone}</span> {fmtMesure(gate?.source)}
      </td>
      <td className={cn('py-0.5 pr-2 tabular-nums', ih.cls)} title={`mesure maison : ${ih.txt}`}>
        <span aria-hidden>{ih.icone}</span> {fmtMesure(gate?.inhouse)}
      </td>
      <td className="py-0.5 pr-2 text-xxs tabular-nums" data-testid={`of-seuil-${code}`}>
        <Seuil t={seuil} />
      </td>
      <td className="py-0.5 text-xxs">
        {accord === null || accord === undefined ? (
          <span className="text-term-faint">indécidable</span>
        ) : accord ? (
          <span className="text-term-dim">accord</span>
        ) : (
          <span className="font-bold text-bias-down">DÉSACCORD</span>
        )}
      </td>
    </tr>
  )
}

/** OF1 / OF2 — les deux gates qui portent un verdict. */
export function OrderFlowGatesPanel() {
  const shadow = useTerminal((s) => s.extras?.orderflow_shadow) as OrderFlowShadow | null | undefined

  return (
    <Panel code="OF1·2" title="Gates order flow — décisionnelles" block="orderflow_shadow" accent="sony"
      detachId="OFG">
      {!shadow ? (
        <p className="p-2 text-xs text-term-faint">— aucune observation publiée</p>
      ) : (
        <div className="flex min-h-0 flex-col gap-1 p-1.5">
          <p className="text-xxs text-term-dim" data-testid="of-resume">{shadow.resume}</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-xxs text-term-faint">
                <th className="text-left font-normal">code</th>
                <th className="text-left font-normal">gate</th>
                <th className="text-left font-normal">proxy</th>
                <th className="text-left font-normal">maison</th>
                <th className="text-left font-normal">seuil</th>
                <th className="text-left font-normal">verdict</th>
              </tr>
            </thead>
            <tbody>
              <LigneGate gate={shadow.b1} {...GATE_LABELS.b1} seuil={shadow.thresholds?.b1} />
              <LigneGate gate={shadow.b2} {...GATE_LABELS.b2} seuil={shadow.thresholds?.b2} />
            </tbody>
          </table>
          {shadow.missing && shadow.missing.length > 0 && (
            <p className="text-xxs text-term-faint" data-testid="of-missing">
              non mesuré : {shadow.missing.join(', ')}
            </p>
          )}
          <p className="text-xxs text-term-faint">source : {shadow.source}</p>
        </div>
      )}
    </Panel>
  )
}

/** OF3 / OF4 — mesurées, JAMAIS gatantes dans cette tranche. Séparées exprès : les mêler aux
 *  décisionnelles laisserait croire qu'elles pèsent sur l'armement, ce qui est faux. */
export function OrderFlowMeasuresPanel() {
  const shadow = useTerminal((s) => s.extras?.orderflow_shadow) as OrderFlowShadow | null | undefined

  return (
    <Panel code="OF3·4" title="Order flow — mesures (non gatantes)" block="orderflow_shadow" accent="sony"
      detachId="OFM">
      <div className="flex flex-col gap-1 p-1.5">
        <p className="text-xxs text-term-faint" data-testid="of-mesures-avertissement">
          observées, seuils NON calibrés — n'entrent dans aucune décision d'armement
        </p>
        {!shadow ? (
          <p className="text-xs text-term-faint">— aucune observation publiée</p>
        ) : (
          <table className="w-full text-xs">
            <tbody>
              {(['b3', 'b4'] as const).map((cle) => (
                <tr key={cle} className="border-t border-term-border/50">
                  <td className="py-0.5 pr-2 font-bold text-term-text">{MEASURE_LABELS[cle].code}</td>
                  <td className="py-0.5 pr-2 text-term-dim">{MEASURE_LABELS[cle].label}</td>
                  <td className="py-0.5 pr-2 tabular-nums text-term-text" data-testid={`of-${cle}`}>
                    {fmtMesure(shadow[cle])}
                  </td>
                  <td className="py-0.5 text-xxs tabular-nums" data-testid={`of-seuil-${MEASURE_LABELS[cle].code}`}>
                    <Seuil t={shadow.thresholds?.[cle]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  )
}
