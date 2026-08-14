"""Adaptation d'un export tiers au tape canonique — Bookmap et les autres (D-060).

**Ce module existe parce qu'on ne connaît pas le format d'export de Bookmap**, et qu'inventer
des noms de colonnes serait exactement ce que la doctrine C2 interdit : un identifiant qui a
l'air vérifié sans l'être. Plutôt que de deviner, on outille la question.

Trois pièces :

1. `sniff(texte)` — lit les premières lignes d'un export RÉEL et rend un diagnostic : séparateur,
   colonnes, **candidats** pour chaque rôle du tape, unité d'horodatage déduite, valeurs de côté
   observées, et ce qui manque. Il ne décide rien : il montre.
2. `Mapping` — la correspondance colonne→rôle, une fois qu'un humain l'a confirmée. Le fichier
   de l'opérateur n'est jamais renommé ni réécrit : on s'adapte à lui.
3. `DIALECTES` — les correspondances connues. **Celle de Bookmap est une HYPOTHÈSE** tant qu'un
   en-tête réel n'a pas été vu ; elle est marquée `verified=False` et le renifleur le dit.

Le piège principal d'un export tiers n'est pas le nom des colonnes — c'est **l'unité de temps**.
Des millisecondes lues comme des secondes placent la séance en l'an 56 000 ; des nanosecondes,
bien plus loin encore. Toutes les fenêtres d'order flow (B1/B4) deviennent alors absurdes tout
en restant crédibles. `sniff` déduit l'unité de l'ORDRE DE GRANDEUR et la montre avant tout
rejeu.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Rôles du tape canonique. `bid_vol`/`ask_vol` sont FACULTATIFS : un export de trades seuls est
# parfaitement rejouable — il produira simplement un tape sans profondeur, ce qui est la vérité.
ROLES_REQUIS = ("timestamp", "price", "volume", "side")
ROLES_FACULTATIFS = ("bid_vol", "ask_vol")

# Noms rencontrés dans les exports courants, par rôle. Cette table sert à PROPOSER, jamais à
# décider : le renifleur affiche ses candidats et c'est un humain qui tranche.
CANDIDATS: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "date", "datetime", "ts", "exchange_time",
                  "exchangetimestamp", "epoch", "utc", "local_time", "recv_time"),
    "price": ("price", "prix", "last", "trade_price", "px"),
    "volume": ("volume", "size", "qty", "quantity", "amount", "trade_size", "vol"),
    "side": ("side", "aggressor", "aggressorside", "direction", "buy_sell", "bidask",
             "is_bid", "isbid", "is_buy", "taker_side"),
    "bid_vol": ("bid_vol", "bidsize", "bid_size", "bidvolume", "bid_qty", "bid"),
    "ask_vol": ("ask_vol", "asksize", "ask_size", "askvolume", "ask_qty", "ask", "offer"),
}

# Valeurs de côté rencontrées → sens agresseur. `is_bid=true` veut dire que l'agression a frappé
# le BID, donc une VENTE : l'inverse de l'intuition, et une erreur qui inverserait tout le delta.
COTES: dict[str, str] = {
    "buy": "BUY", "b": "BUY", "bid": "SELL", "sell": "SELL", "s": "SELL", "ask": "BUY",
    "offer": "BUY", "true": "BUY", "false": "SELL", "1": "BUY", "0": "SELL",
    "up": "BUY", "down": "SELL", "a": "BUY",
}

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


@dataclass(frozen=True)
class Mapping:
    """Correspondance colonne→rôle, confirmée par un humain. `side_values` traduit les valeurs
    observées ; `time_unit` est explicite parce que la deviner à chaque ligne serait fragile."""
    columns: dict[str, str]                       # rôle → nom de colonne dans LE fichier
    time_unit: str = "s"                          # s · ms · us · ns · iso
    side_values: dict[str, str] = field(default_factory=lambda: dict(COTES))
    delimiter: str = ","
    label: str = "personnalisé"
    verified: bool = False                        # un humain a-t-il confirmé sur un export réel ?


# Dialectes connus. Le seul VÉRIFIÉ est le format canonique du générateur maison.
DIALECTES: dict[str, Mapping] = {
    "cholismo": Mapping(
        columns={r: r for r in ROLES_REQUIS + ROLES_FACULTATIFS},
        time_unit="s", label="tape canonique Cholismo", verified=True),
    # HYPOTHÈSE — jamais confrontée à un export réel. Les noms viennent de conventions
    # courantes, pas d'un fichier observé. `verified=False` : le renifleur le dira, et rien
    # ici ne doit être pris pour une vérité tant qu'un en-tête n'a pas été collé.
    "bookmap": Mapping(
        columns={"timestamp": "Time", "price": "Price", "volume": "Size",
                 "side": "AggressorSide"},
        time_unit="ms", label="Bookmap (HYPOTHÈSE, non confirmée)", verified=False),
}


def _norm(nom: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (nom or "").strip().lower())


def _sniff_delimiter(texte: str) -> str:
    """Le séparateur se DÉDUIT du nombre de colonnes obtenues, pas d'un pari : un export
    européen sort volontiers en `;`, un export d'outil de trading parfois en tabulation."""
    premiere = texte.splitlines()[0] if texte.splitlines() else ""
    return max((",", ";", "\t", "|"), key=lambda d: premiere.count(d))


def _time_unit(valeurs: list[str]) -> tuple[str, str]:
    """Unité d'horodatage déduite de l'ORDRE DE GRANDEUR. C'est le piège principal d'un export
    tiers : des millisecondes lues comme des secondes placent la séance en l'an 56 000, et
    toutes les fenêtres d'order flow deviennent absurdes en restant crédibles."""
    for v in valeurs:
        texte = (v or "").strip()
        if _ISO_RE.match(texte):
            return "iso", f"horodatage ISO (« {texte[:19]} ») — à convertir en epoch"
        if _NUM_RE.match(texte):
            n = abs(float(texte))
            if n > 1e17:
                return "ns", "ordre de grandeur ≈ 1e18 → NANOsecondes"
            if n > 1e14:
                return "us", "ordre de grandeur ≈ 1e15 → MICROsecondes"
            if n > 1e11:
                return "ms", "ordre de grandeur ≈ 1e12 → MILLIsecondes"
            if n > 1e8:
                return "s", "ordre de grandeur ≈ 1e9 → secondes epoch"
            return "?", f"valeur « {texte} » trop petite pour un epoch — horloge relative ?"
    return "?", "aucune valeur d'horodatage lisible dans l'échantillon"


@dataclass
class Diagnostic:
    """Ce que le renifleur a VU. Il ne décide rien : c'est un humain qui confirme."""
    delimiter: str
    columns: list[str]
    rows_read: int
    candidates: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    time_unit: str = "?"
    time_note: str = ""
    side_values: list[str] = field(default_factory=list)
    side_unknown: list[str] = field(default_factory=list)
    sample: list[dict[str, str]] = field(default_factory=list)

    @property
    def resume(self) -> str:
        if self.missing:
            return (f"{len(self.columns)} colonnes · rôle(s) NON RÉSOLU(S) : "
                    f"{', '.join(self.missing)} — à désigner à la main")
        return (f"{len(self.columns)} colonnes · tous les rôles requis résolus · "
                f"temps = {self.time_unit}")

    def proposed(self) -> Optional[Mapping]:
        """La correspondance PROPOSÉE — `None` si un rôle requis reste ambigu. On ne choisit
        pas à la place de l'opérateur quand plusieurs colonnes sont plausibles."""
        if self.missing or self.time_unit == "?":
            return None
        cols = {r: self.candidates[r][0] for r in ROLES_REQUIS if self.candidates.get(r)}
        for r in ROLES_FACULTATIFS:
            if self.candidates.get(r):
                cols[r] = self.candidates[r][0]
        return Mapping(columns=cols, time_unit=self.time_unit, delimiter=self.delimiter,
                       label="proposé par le renifleur", verified=False)


def sniff(texte: str, *, max_rows: int = 50) -> Optional[Diagnostic]:
    """Lit un échantillon d'export et rend un diagnostic. `None` si ce n'est pas un CSV lisible.

    Aucune écriture, aucun rejeu : c'est une LECTURE de reconnaissance, à faire avant tout le
    reste sur un fichier dont on ne connaît pas le format."""
    if not isinstance(texte, str) or not texte.strip():
        return None
    delim = _sniff_delimiter(texte)
    try:
        reader = csv.DictReader(io.StringIO(texte), delimiter=delim)
        entetes = reader.fieldnames
        if not entetes:
            return None
        lignes = [r for _, r in zip(range(max_rows), reader)]
    except (csv.Error, ValueError):
        return None

    normalises = {_norm(c): c for c in entetes}
    candidats: dict[str, list[str]] = {}
    for role, noms in CANDIDATS.items():
        trouves = [normalises[_norm(n)] for n in noms if _norm(n) in normalises]
        # Repli : une colonne dont le nom CONTIENT le mot-clé (« Trade Price », « Bid Size »).
        if not trouves:
            trouves = [c for c in entetes
                       if any(_norm(n) and _norm(n) in _norm(c) for n in noms)]
        # Dédoublonnage en gardant l'ordre : « bidsize » et « bid_size » se normalisent pareil
        # et désignaient la MÊME colonne deux fois, ce qui affichait une fausse ambiguïté sur
        # une détection pourtant correcte — de quoi faire douter d'un bon résultat.
        uniques = list(dict.fromkeys(trouves))          # dédoublonne en gardant l'ordre
        if uniques:
            candidats[role] = uniques

    manquants = [r for r in ROLES_REQUIS if r not in candidats]
    unit, note = ("?", "colonne d'horodatage non identifiée")
    if "timestamp" in candidats:
        col = candidats["timestamp"][0]
        unit, note = _time_unit([str(ligne.get(col, "")) for ligne in lignes[:10]])

    vus: list[str] = []
    inconnus: list[str] = []
    if "side" in candidats:
        col = candidats["side"][0]
        for ligne in lignes:
            brut = str(ligne.get(col, "")).strip()
            if brut and brut not in vus:
                vus.append(brut)
                if brut.lower() not in COTES:
                    inconnus.append(brut)

    return Diagnostic(delimiter=delim, columns=list(entetes), rows_read=len(lignes),
                      candidates=candidats, missing=manquants, time_unit=unit, time_note=note,
                      side_values=vus, side_unknown=inconnus, sample=lignes[:3])


def to_seconds(valeur: Any, unit: str) -> Optional[float]:
    """Horodatage → secondes epoch, selon l'unité CONFIRMÉE. `None` si illisible : on ne devine
    pas ligne à ligne, la devinette n'a lieu qu'une fois, au reniflage."""
    texte = str(valeur or "").strip()
    if not texte:
        return None
    if unit == "iso":
        from datetime import datetime, timezone       # calendrier, pas horloge : `now` jamais lu
        try:
            dt = datetime.fromisoformat(texte.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    if not _NUM_RE.match(texte):
        return None
    n = float(texte)
    facteur = {"s": 1.0, "ms": 1e3, "us": 1e6, "ns": 1e9}.get(unit)
    return n / facteur if facteur else None


def to_side(valeur: Any, table: dict[str, str]) -> Optional[str]:
    """Valeur de côté → BUY/SELL. `None` si inconnue — jamais un côté par défaut : se tromper
    de sens inverse le delta agresseur, et le nombre reste parfaitement crédible."""
    return table.get(str(valeur or "").strip().lower())
