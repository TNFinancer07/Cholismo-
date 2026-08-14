"""Pont Stream Deck — projection des touches et liste blanche d'actions (D-119).

Le daemon vit dans `workers/streamdeck_bridge.py`. Ce module-ci est **pur** : il transforme l'état
du terminal en tuiles, et valide les actions reçues. Séparés parce que seule cette partie peut
être fausse hors matériel.

---

**⛔ AUCUNE touche ne peut enregistrer une décision GO — et ce n'est pas un oubli.**

Un `GO` exige aujourd'hui deux choses que le serveur vérifie : Phase 0 `OPEN`, et un **self-check
cognitif** à quatre réponses (`sleep_ok`, `focus_ok`, `no_tilt`, `plan_written`). Une touche
physique ne peut pas attester qu'on a dormi, qu'on est concentré, qu'on n'est pas en tilt et que
le plan est écrit. Lui faire poster un self-check pré-rempli reviendrait à **automatiser le
mensonge** que la gate existe pour empêcher.

Plus profondément : `CLAUDE §6` — la discipline est dans l'infra, pas dans la volonté. Une
décision réduite à un réflexe de pouce sur un boîtier à côté du clavier est l'inverse exact du
harnais que tout ce terminal construit. Le Stream Deck **montre** et **confirme** ; il ne décide
pas.

La liste blanche est donc **structurelle** : une action absente ne peut pas être exécutée, et un
test relit cette source pour refuser tout vocabulaire d'ordre.
"""
from __future__ import annotations

from typing import Any, Optional

#: Actions autorisées. Toutes RÉVERSIBLES et sans effet sur une décision de trading.
#: Ajouter une entrée ici est une décision d'architecture, pas un réglage.
ACTIONS = {
    "audio_toggle": "coupe ou active les alertes sonores (D-115)",
    "detach_panel": "ouvre un panneau en fenêtre indépendante (D-117)",
    "set_workspace": "change de disposition d'espace de travail",
    "focus_terminal": "ramène la fenêtre principale au premier plan",
}

#: Refus explicites — nommés pour que le message dise POURQUOI, pas « action inconnue ».
REFUSED = {
    "decision_go": ("un GO exige un self-check cognitif à quatre réponses et Phase 0 OPEN — "
                    "une touche ne peut pas les attester (§2.1, §6)"),
    "decision_no_go": ("un NO-GO se consigne avec son motif : une touche muette produirait un "
                       "journal sans raison, donc inexploitable en calibration"),
    "place_order": "le terminal ne passe aucun ordre (§2.1)",
    "arm_setup": ("l'armement est PRODUIT par le moteur déterministe, il ne se déclenche pas à "
                  "la main — le forcer contournerait les 30 contrôles"),
}


def validate_action(name: Any, payload: Any = None) -> tuple[bool, Optional[str]]:
    """`(autorisé, motif de refus)`. Un refus nommé est actionnable ; « action inconnue » ne
    l'est pas."""
    if not isinstance(name, str) or not name:
        return False, "action sans nom"
    if name in REFUSED:
        return False, REFUSED[name]
    if name not in ACTIONS:
        return False, f"action « {name} » hors liste blanche"
    if name == "detach_panel" and not (isinstance(payload, dict) and payload.get("panel")):
        return False, "detach_panel exige un panneau"
    return True, None


def _tile(key: str, label: str, value: str, status: str) -> dict[str, Any]:
    """`status` est un NOM, pas une couleur : le pont ne décide pas du rendu, et un boîtier
    monochrome doit rester lisible (§3 — jamais la couleur seule)."""
    return {"key": key, "label": label, "value": value, "status": status}


def _fmt(v: Any) -> str:
    """`—` pour tout ce qui n'est pas un nombre fini. Un `0` sur une touche serait lu comme une
    mesure, et une touche se lit d'un coup d'œil — sans infobulle pour nuancer."""
    if isinstance(v, bool):
        return "oui" if v else "non"
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)[:12]
    return "—" if f != f else f"{round(f, 3)}"


def build_keys(state: Any) -> list[dict[str, Any]]:
    """Tuiles du boîtier. Ne lève jamais : un pont qui casse doit s'éteindre, pas remonter.

    Quatre statuts et jamais deux : `OK`, `WARN`, `ALERT`, `UNKNOWN`. **`UNKNOWN` n'est pas
    `OK`** — une touche verte sur une mesure absente ferait exactement ce que tout ce dépôt
    s'emploie à empêcher, mais sur un objet qu'on regarde du coin de l'œil.
    """
    s = state if isinstance(state, dict) else {}
    extras = s.get("extras") if isinstance(s.get("extras"), dict) else {}
    shadow = extras.get("orderflow_shadow") if isinstance(extras.get("orderflow_shadow"), dict) else {}
    vacuum = extras.get("liquidity_vacuum") if isinstance(extras.get("liquidity_vacuum"), dict) else {}
    prot = s.get("protection") if isinstance(s.get("protection"), dict) else {}

    def gate(code: str) -> dict[str, Any]:
        g = shadow.get(code) if isinstance(shadow.get(code), dict) else {}
        v = g.get("verdict_inhouse")
        statut = "UNKNOWN" if v is None else ("OK" if v else "ALERT")
        return _tile(code.upper().replace("B", "OF"), f"OF{code[-1]}", _fmt(g.get("inhouse")), statut)

    vide = vacuum.get("vacuum")
    verrou = bool(prot.get("locked"))

    return [
        # L'état du setup en premier : c'est la seule touche qu'on cherche des yeux.
        _tile("SETUP", "setup",
              "VERROUILLÉ" if verrou else ("ARMÉ" if s.get("armed") else "attente"),
              "ALERT" if verrou else ("OK" if s.get("armed") else "UNKNOWN")),
        gate("b1"), gate("b2"),
        _tile("OF3", "OF3", _fmt(shadow.get("b3")), "UNKNOWN" if shadow.get("b3") is None else "OK"),
        _tile("OF4", "OF4", _fmt(shadow.get("b4")), "UNKNOWN" if shadow.get("b4") is None else "OK"),
        _tile("LOCK", "verrous F6/F7",
              str(prot.get("lock_reason") or ("aucun" if "locked" in prot else "—"))[:14],
              "ALERT" if verrou else ("OK" if "locked" in prot else "UNKNOWN")),
        _tile("VACUUM", "vide carnet",
              "—" if vide is None else ("OUI" if vide else "non"),
              "UNKNOWN" if vide is None else ("WARN" if vide else "OK")),
    ]
