"""`python -m app.providers` — lire le registre sans ouvrir un fichier Python (D-057, /polish).

Le registre transcrit deux specs de ~50 lignes. Tant qu'on ne peut le consulter qu'en important
des modules, il n'est pas consultable : la question qu'on se pose devant ces artefacts — « qu'est
-ce que je peux collecter aujourd'hui, qu'est-ce qui est bloqué, et par quoi ? » — n'a pas de
réponse à portée de main. C'est la découvrabilité de la Loop 5, pas une nouvelle fonctionnalité :
lecture seule, aucun appel réseau, aucun ordre nulle part (§2.1).

Rendu volontairement dense et monospace, **sans couleur** : le statut passe par un glyphe ET le
texte du motif, jamais par un signal unique (§3). Une ligne non collectable affiche toujours
POURQUOI — jamais un symbole sec que l'opérateur devrait décoder.

Vues : `python -m app.providers` (par dimension) · `python -m app.providers arbitrages`.
"""
from __future__ import annotations

import sys
import time

from . import catalog as cat

WIDTH = 118
GLYPHS = {"ok": "✓", "catalogue": "≈", "bloque": "✕", "calcul": "·"}
# Libellés courts : la colonne fournisseur est fixe, et `PHILADELPHIA_FED` (16) décalait toute
# la ligne — une colonne qui déborde par intermittence casse la lecture en tableau.
_PROVIDER_LABEL = {cat.Provider.PHILADELPHIA_FED: "PHIL_FED", cat.Provider.CFTC_SOCRATA: "CFTC",
                   cat.Provider.BUNDESBANK: "BUBA"}


def _glyph(spec: cat.SeriesSpec, reason: str | None) -> str:
    if reason is None:
        return GLYPHS["ok"]
    if spec.kind in (cat.Kind.DERIVED, cat.Kind.PARAMETER):
        return GLYPHS["calcul"]
    return GLYPHS["catalogue"] if spec.confidence is cat.Confidence.C2 else GLYPHS["bloque"]


def _cut(text: str, width: int) -> str:
    """Troncature VISIBLE : une ligne coupée en silence se lit comme une ligne complète."""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _row(spec: cat.SeriesSpec) -> str:
    reason = cat.fetch_block_reason(spec.key)
    if reason is None:
        right = spec.identifier or "—"
    elif spec.confidence is cat.Confidence.C2 and spec.catalog_hint:
        # Sur une ligne à relever, l'information utile est OÙ relever — c'est elle qui doit
        # survivre à la troncature, pas la phrase générique qui la précède.
        right = f"C2 · {spec.catalog_hint}"
    else:
        right = reason
    provider = _PROVIDER_LABEL.get(spec.provider, spec.provider.value)
    head = f"  {_glyph(spec, reason)} {spec.key:<16} {spec.leg.value:<6} {provider:<10} "
    return _cut(head + right, WIDTH)


def _section(title: str, subtitle: str = "") -> str:
    line = title if not subtitle else f"{title}{' ' * max(1, WIDTH - len(title) - len(subtitle))}{subtitle}"
    return f"\n{_cut(line, WIDTH)}\n{'─' * WIDTH}"


def render(now: float, view: str = "dimensions") -> str:
    total = len(cat.CATALOG)
    collectables = len(cat.fetchable())
    # Trois familles bien distinctes, et les confondre est le piège que les specs signalent :
    # une C3 n'est pas forcément « une donnée qui manque », et un paramètre ne manque jamais.
    a_relever = [s for s in cat.CATALOG
                 if s.kind is cat.Kind.OBSERVED and s.confidence is cat.Confidence.C2]
    bloquees = [s for s in cat.CATALOG
                if s.kind is cat.Kind.OBSERVED and s.confidence is cat.Confidence.C3]
    parametres = [s for s in cat.CATALOG if s.kind is cat.Kind.PARAMETER]

    out = [
        "CHOLISMO · registre des séries macro de Youssef — D1–D5 × Arb 1–6 (D-057)",
        f"{total} lignes · {collectables} collectables · {len(a_relever)} identifiants à "
        f"relever · {len(bloquees)} sources bloquées · {len(parametres)} paramètres à "
        "calibrer · 0 € / mois",
        f"  {GLYPHS['ok']} collectable   {GLYPHS['catalogue']} identifiant à relever   "
        f"{GLYPHS['bloque']} bloqué   {GLYPHS['calcul']} calculé ou paramètre "
        "— le motif est toujours affiché",
        "  lecture seule · aucun appel réseau · aucun ordre (§2.1)",
    ]

    if view == "arbitrages":
        for arb in cat.ARBITRAGES:
            rows = cat.by_arbitrage().get(arb.arb_id, ())
            ok = sum(1 for s in rows if cat.fetch_block_reason(s.key) is None)
            out.append(_section(f"Arb {arb.arb_id} · {arb.name}",
                                f"{arb.source_dim} · {arb.horizon} · {arb.threshold_label} · "
                                f"{arb.status} · {ok}/{len(rows)} collectables"))
            out.append(f"  {_cut(arb.formula, WIDTH - 2)}")
            out.extend(_row(s) for s in rows)
    else:
        by_dim = cat.by_dimension()
        for code, dim in cat.DIMENSIONS.items():
            rows = by_dim.get(code, ())
            ok = sum(1 for s in rows if cat.fetch_block_reason(s.key) is None)
            role = {"A": "type A directionnel", "B": "type B modulateur",
                    "ABSORBED": f"absorbé par {dim.absorbed_by}, poids 0"}[dim.kind]
            out.append(_section(f"{code} · {dim.label}",
                                f"{role} · horizon {dim.horizon} · "
                                f"TTL {dim.ttl_s / 86400:.0f} j · {ok}/{len(rows)} collectables"))
            out.extend(_row(s) for s in rows)

    out.append(_section("À relever au catalogue du fournisseur",
                        f"{len(a_relever)} ligne(s) — même protocole, une session suffit"))
    out.extend(f"  {GLYPHS['catalogue']} {s.key:<16} {_cut(s.catalog_hint, WIDTH - 22)}"
               for s in a_relever)

    out.append(_section("Incohérences ouvertes",
                        f"{len(cat.KNOWN_CONFLICTS)} — signalées, volontairement NON corrigées"))
    for conflict in cat.KNOWN_CONFLICTS:
        out.append(f"  ! {conflict['topic']:<26} {_cut(conflict['question'], WIDTH - 32)}")
        out.append(f"    valeurs  {_cut(str(conflict['values']), WIDTH - 14)}")
        out.append(f"    statut   {conflict['status']} · {_cut(conflict['code_actuel'], WIDTH - 24)}")

    roll = cat.bundei_roll_state(now)
    out.append(_section("Échéance du Bund€i", f"{roll['isin']} · {roll['maturity']}"))
    out.append(f"  {'!' if roll['status'] != 'OK' else GLYPHS['ok']} {roll['status']} — "
               f"{_cut(roll['message'], WIDTH - 24)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    view = "arbitrages" if args and args[0].startswith("arb") else "dimensions"
    print(render(time.time(), view))          # horloge lue ICI, au bord — jamais dans le registre
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
