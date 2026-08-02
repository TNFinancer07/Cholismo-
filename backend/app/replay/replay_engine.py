"""Mode Replay local — rejouer un tape enregistré depuis un CSV (Étape 1).

Interface publique conservée telle que demandée :

    ReplayEngine(filepath, on_tick_callback).start(speed_delay=0.0)

Ce que la structure de départ faisait, et pourquoi c'est corrigé ici — chaque point est un
défaut qui se paie en silence, ce que ce terminal refuse (§3) :

1. **Une ligne malformée tuait tout le replay.** `float(row['price'])` lève au milieu du flux,
   après avoir déjà émis N ticks. Le consommateur a reçu un tape TRONQUÉ qu'il croit complet.
   Ici une ligne illisible est ÉCARTÉE et COMPTÉE, comme dans les parsers du paquet `providers`.
2. **`bid_vol` absent devenait `0`.** C'est l'erreur que ce dépôt a déjà payée en D-055 : « hors
   profondeur ≠ taille nulle ». Zéro volume est un FAIT (personne n'est là) ; absent est un
   INCONNU. Les confondre fabrique une liquidité qui n'a jamais existé — ou son contraire.
   Une colonne absente ou vide rend `None`, jamais `0.0`.
3. **Le temps n'était pas vérifié.** Un horodatage vide, illisible ou qui RECULE produisait un
   marché qui remonte le temps. Tout le Niveau 2 order flow (D-055/D-056) calcule sur des
   fenêtres temporelles : un replay non monotone y produit des mesures absurdes mais crédibles.
   Les ticks hors séquence sont écartés et comptés.
4. **`time.sleep(speed_delay)` n'est pas un replay.** Une cadence UNIFORME ne ressemble à aucun
   tape : le marché arrive par rafales et par trous, et c'est précisément ce que le détecteur
   `TAPE_BURST` cherche. Rejouer à intervalle fixe rendrait donc le phénomène qu'on veut tester
   structurellement inobservable. `speed_delay` est conservé (compatibilité), mais `speed`
   honore les INTERVALLES RÉELS du fichier.
5. **Rien ne pouvait l'arrêter.** `stop()` interrompt proprement entre deux ticks.
6. **Aucun compte rendu.** `start()` rend un `ReplaySummary` : émis, écartés, et pourquoi.

Ce module est SYNCHRONE et sans horloge de marché : il ne lit `time` que pour cadencer. Le
brancher derrière `MarketDataSource` (la couture unique du terminal, CLAUDE §4) est l'étape
suivante et n'est volontairement pas faite ici.
"""
from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# Un tape de session tient dans quelques centaines de milliers de prints. Au-delà, ce n'est plus
# un enregistrement de séance : c'est un fichier qu'on n'a pas voulu lire, et le charger
# mangerait la mémoire sans que personne l'ait demandé.
MAX_TICKS = 5_000_000
SIDES = ("BUY", "SELL")


@dataclass
class ReplaySummary:
    """Ce que le replay a réellement fait. Sans ce compte rendu, un fichier à moitié pourri
    produit un tape amputé qui se lit comme un tape complet."""
    emitted: int = 0
    skipped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None
    stopped_early: bool = False

    def _note(self, motif: str) -> None:
        self.skipped += 1
        self.reasons[motif] = self.reasons.get(motif, 0) + 1

    @property
    def resume(self) -> str:
        """L'état en UNE ligne — un dict de compteurs n'est pas un message."""
        if not self.skipped:
            base = f"{self.emitted} ticks rejoués · aucun écarté"
        else:
            detail = ", ".join(f"{n}× {m}" for m, n in sorted(self.reasons.items(),
                                                              key=lambda kv: -kv[1]))
            base = f"{self.emitted} ticks rejoués · {self.skipped} ÉCARTÉS : {detail}"
        return base + (" · ARRÊTÉ AVANT LA FIN" if self.stopped_early else "")

    def __str__(self) -> str:
        return self.resume


def _float(raw: Any) -> Optional[float]:
    """`None` = pas une valeur. Une chaîne vide ou un marqueur de trou n'est pas un zéro."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", ".", ":", "NA", "N/A", "null", "None"):
        return None
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _timestamp(raw: Any) -> Optional[float]:
    """Horodatage en secondes epoch. Accepte aussi les millisecondes : un tape exporté en ms
    interprété en secondes placerait la séance en l'an 56 000 — l'erreur est silencieuse et
    fatale pour toute fenêtre temporelle."""
    value = _float(raw)
    if value is None or value <= 0:
        return None
    return value / 1000.0 if value > 1e11 else value


class ReplayEngine:
    """Rejoue un CSV de ticks vers un callback. Un tick émis est un tick VALIDE : tout ce qui
    ne l'est pas est écarté et compté, jamais deviné."""

    def __init__(self, filepath: str, on_tick_callback: Callable[[dict], Any]):
        self.filepath = filepath
        self.on_tick_callback = on_tick_callback
        self._stop = False

    def stop(self) -> None:
        """Demande l'arrêt : le replay s'interrompt entre deux ticks, jamais au milieu d'un."""
        self._stop = True

    def start(self, speed_delay: float = 0.0, *, speed: Optional[float] = None,
              max_ticks: int = MAX_TICKS) -> ReplaySummary:
        """Rejoue le fichier.

        `speed_delay` : pause FIXE entre deux ticks (compatibilité — utile pour regarder défiler,
        inutile pour reproduire un marché).
        `speed` : multiplicateur du temps RÉEL du fichier (`speed=2` = deux fois plus vite).
        C'est le seul mode qui reproduit les rafales et les trous, donc le seul sur lequel un
        détecteur de burst puisse être jugé. `speed` l'emporte sur `speed_delay`.
        """
        summary = ReplaySummary()
        self._stop = False
        precedent: Optional[float] = None
        # `newline=""` est exigé par le module csv (sinon un champ multiligne casse le parsing) ;
        # l'encodage est explicite, sinon il dépend de la machine qui lit — un CSV écrit sous
        # Linux et rejoué sous Windows n'aurait pas le même sens.
        with open(self.filepath, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return summary                              # fichier vide : rien à rejouer
            manquantes = {"timestamp", "price", "volume", "side"} - set(reader.fieldnames)
            if manquantes:
                raise ValueError(
                    f"colonnes obligatoires absentes du CSV : {', '.join(sorted(manquantes))} — "
                    "un replay amputé de son prix ou de son horodatage n'est pas un replay.")
            for row in reader:
                if self._stop:
                    summary.stopped_early = True
                    break
                if summary.emitted >= max_ticks:
                    summary.stopped_early = True
                    summary._note("plafond de ticks atteint")
                    break
                tick, motif = self._parse(row, precedent)
                if tick is None:
                    summary._note(motif or "ligne illisible")
                    continue
                self._cadence(tick["timestamp"], precedent, speed_delay, speed)
                precedent = tick["timestamp"]
                summary.first_ts = summary.first_ts if summary.first_ts is not None \
                    else tick["timestamp"]
                summary.last_ts = tick["timestamp"]
                summary.emitted += 1
                # L'exception du CALLBACK n'est pas rattrapée : c'est un défaut du
                # consommateur, pas une ligne pourrie du fichier. L'avaler laisserait un bug
                # applicatif passer pour une donnée manquante.
                self.on_tick_callback(tick)
        return summary

    # -- internes --

    def _parse(self, row: dict, precedent: Optional[float]) -> tuple[Optional[dict], str]:
        ts = _timestamp(row.get("timestamp"))
        if ts is None:
            return None, "horodatage illisible"
        if precedent is not None and ts < precedent:
            # Un tape qui recule fabrique des fenêtres négatives : toutes les mesures d'order
            # flow qui en dépendent deviendraient absurdes tout en restant crédibles.
            return None, "horodatage NON MONOTONE (le tape recule)"
        price = _float(row.get("price"))
        if price is None or price <= 0:
            return None, "prix illisible ou non positif"
        volume = _float(row.get("volume"))
        if volume is None or volume < 0 or volume != int(volume):
            return None, "volume illisible ou non entier"
        side = str(row.get("side", "")).strip().upper()
        if side not in SIDES:
            return None, f"côté inconnu (attendu {'/'.join(SIDES)})"
        return {
            "timestamp": ts,
            "price": price,
            "volume": int(volume),
            "side": side,
            # `None` et non `0.0` : une profondeur absente est INCONNUE, pas vide (D-055).
            "bid_vol": _float(row.get("bid_vol")),
            "ask_vol": _float(row.get("ask_vol")),
        }, ""

    @staticmethod
    def _cadence(ts: float, precedent: Optional[float], speed_delay: float,
                 speed: Optional[float]) -> None:
        if speed is not None and speed > 0:
            if precedent is not None:
                attente = (ts - precedent) / speed
                if attente > 0:
                    time.sleep(min(attente, 5.0))           # borne : un trou d'une heure dans
            return                                          # le fichier ne gèle pas la session
        if speed_delay > 0:
            time.sleep(speed_delay)
