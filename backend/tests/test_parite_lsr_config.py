"""VERROU DE PARITÉ — `lsr-engine/src/config.ts` ↔ constantes Python (D-072).

Ce fichier **lit le TypeScript** et échoue si le Python ne dit pas la même chose.

**Pourquoi un test et pas une relecture.** Les huit dernières passes de parité ont toutes trouvé
la même chose : non pas une mauvaise valeur, mais **la même valeur écrite à deux endroits**, puis
corrigée d'un seul côté. Une relecture attrape ça le jour où on la fait ; un test l'attrape le
jour où ça arrive. Et surtout : une divergence de seuil ne casse aucun test métier — elle produit
des trades légèrement différents, en silence, pendant des semaines.

**Trois propriétés, dans l'ordre d'importance :**

1. **Aucune constante du TS ne peut être IGNORÉE.** Chaque clé lue dans `config.ts` est soit
   comparée à une grandeur Python, soit inscrite au `NON_PORTE` avec un motif et la décision qui
   la suit. Une clé neuve côté TS fait tomber le test tant que personne n'a tranché son sort.
2. **Ce qui est comparé doit être ÉGAL**, au flottant près.
3. **Le registre `NON_PORTE` ne peut pas pourrir** : une entrée qui a fini par être portée fait
   tomber le test, pour qu'on la retire au lieu de la laisser mentir.

Le parseur est volontairement bête (regex + arithmétique de produits/sommes) : il lit des
littéraux, pas du TypeScript. S'il ne comprend plus le fichier, il le DIT — il ne devine pas.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import config, lsr_frontiers, lsr_tuning
from app.risk_sizer import APEX_EOD_50K

CONFIG_TS = Path(__file__).resolve().parents[2] / "lsr-engine" / "src" / "config.ts"


# --- Lecture du TypeScript --------------------------------------------------------------------

def _nombre(brut: str) -> float:
    """`2 * 60_000` → 120000.0, `50_000` → 50000.0, `0.4` → 0.4.

    Sommes de produits uniquement — c'est tout ce que `config.ts` contient, et refuser le reste
    vaut mieux qu'un `eval` qui exécuterait n'importe quoi lu sur le disque."""
    total = 0.0
    for terme in brut.replace("_", "").split("+"):
        produit = 1.0
        for facteur in terme.split("*"):
            produit *= float(facteur.strip())
        total += produit
    return total


def _bloc(source: str, nom: str) -> dict[str, float]:
    """Paires `cle: <nombre>` du littéral d'objet nommé. Les lignes non numériques (chaînes,
    références comme `MES: MES_TUNING`) sont ignorées : ce ne sont pas des grandeurs."""
    debut = source.index(f"{nom}")
    ouvrante = source.index("{", debut)
    profondeur, fin = 0, ouvrante
    for i in range(ouvrante, len(source)):
        if source[i] == "{":
            profondeur += 1
        elif source[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                fin = i
                break
    corps = source[ouvrante + 1:fin]
    trouve: dict[str, float] = {}
    for cle, valeur in re.findall(r"(\w+)\s*:\s*([0-9_.\s*+]+?)\s*[,}\n]", corps):
        try:
            trouve[cle] = _nombre(valeur)
        except ValueError:
            continue
    return trouve


@pytest.fixture(scope="module")
def ts() -> str:
    assert CONFIG_TS.exists(), (
        f"{CONFIG_TS} introuvable — le moteur de référence a bougé ou disparu. Ce verrou ne "
        "peut pas se prononcer sans lui : le RÉPARER, pas le désactiver.")
    return CONFIG_TS.read_text(encoding="utf-8")


def test_le_parseur_comprend_encore_le_fichier(ts):
    """Garde-fou du garde-fou : un parseur qui ne trouve plus rien passerait tous les autres
    tests au vert en ne comparant RIEN. On exige donc un plancher de clés dans chaque bloc."""
    assert len(_bloc(ts, "MES_TUNING")) >= 14, "bloc MES_TUNING illisible ou vidé"
    assert len(_bloc(ts, "MNQ_TUNING")) >= 14, "bloc MNQ_TUNING illisible ou vidé"
    assert len(_bloc(ts, "DEFAULT_CONFIG")) >= 17, "bloc DEFAULT_CONFIG illisible ou vidé"
    assert len(_bloc(ts, "APEX_EOD_50K")) >= 4, "preset APEX_EOD_50K illisible ou vidé"


def test_lecture_des_nombres():
    """Le parseur d'abord, puisque tout le reste en dépend."""
    assert _nombre("50_000") == 50_000
    assert _nombre("2 * 60_000") == 120_000
    assert _nombre("24 * 60 * 60_000") == 86_400_000
    assert _nombre("0.4") == 0.4


# --- 1. Calibration par instrument -------------------------------------------------------------

def _snake(camel: str) -> str:
    """`f4MaxSpreadTicks` → `f4_max_spread_ticks`. Mécanique, donc non falsifiable : les champs
    de `InstrumentTuning` portent EXACTEMENT ce nom des deux côtés (D-069)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()


@pytest.mark.parametrize("bloc_ts, tuning_py", [("MES_TUNING", lsr_tuning.MES_TUNING),
                                                ("MNQ_TUNING", lsr_tuning.MNQ_TUNING)])
def test_la_calibration_par_instrument_est_IDENTIQUE(ts, bloc_ts, tuning_py):
    attendu = _bloc(ts, bloc_ts)
    ecarts = []
    for cle, valeur in attendu.items():
        champ = _snake(cle)
        if not hasattr(tuning_py, champ):
            ecarts.append(f"{bloc_ts}.{cle} → `{champ}` ABSENT du modèle Python")
            continue
        obtenu = float(getattr(tuning_py, champ))
        if obtenu != valeur:
            ecarts.append(f"{bloc_ts}.{cle} : TS={valeur} · Python.{champ}={obtenu}")
    assert ecarts == [], "\n".join(ecarts)


def test_aucun_champ_Python_n_est_INVENTE(ts):
    """Sens inverse : un champ que le Python porte et que le TS ignore serait un seuil sorti de
    nulle part, appliqué en production sans contrepartie dans le moteur de référence."""
    connus = {_snake(c) for c in _bloc(ts, "MES_TUNING")}
    en_trop = sorted(set(lsr_tuning.MES_TUNING.model_dump()) - connus)
    assert en_trop == [], f"champs Python sans équivalent TypeScript : {en_trop}"


def _sous_blocs(source: str, nom: str) -> dict[str, dict[str, float]]:
    """`INSTRUMENT_SPECS` est IMBRIQUÉ (`MES: { tickSize… }, MNQ: { tickSize… }`). Le lire à plat
    ferait garder la dernière valeur de chaque clé homonyme — donc comparer MNQ en croyant
    comparer MES, et déclarer la parité sur un instrument jamais vérifié. Trouvé par ce test
    lui-même, à sa première exécution."""
    debut = source.index(nom)
    fin = source.index("};", debut)
    return {inst: {c: _nombre(v) for c, v in re.findall(r"(\w+)\s*:\s*([0-9_.\s*+]+)", corps)}
            for inst, corps in re.findall(r"(\w+)\s*:\s*\{([^}]*)\}", source[debut:fin])}


def test_les_specs_dechange_CME_sont_IDENTIQUES(ts):
    specs = _sous_blocs(ts, "INSTRUMENT_SPECS")
    assert set(specs) == set(lsr_tuning.INSTRUMENT_SPECS), (
        f"instruments TS {sorted(specs)} ≠ Python {sorted(lsr_tuning.INSTRUMENT_SPECS)}")
    for instrument, attendu in specs.items():
        py = lsr_tuning.INSTRUMENT_SPECS[instrument]
        assert attendu["tickSize"] == py.tick_size, instrument
        assert attendu["tickValue"] == py.tick_value, instrument


# --- 2. Configuration globale ------------------------------------------------------------------

#: Clé TS → grandeur Python équivalente, exprimée DANS L'UNITÉ DU TS (ms, fraction…).
#: La conversion est écrite ici plutôt que dans le code : c'est le seul endroit où les deux
#: systèmes d'unités se rencontrent, et le rendre visible évite qu'un facteur 1000 se cache.
PORTE: dict[str, object] = {
    "riskFractionOfCapital": lambda: config.RISK_FRACTION_OF_CAPITAL,
    "bufferDivisor": lambda: float(config.RISK_BUFFER_DIVISOR),
    "f2CircuitThreshold": lambda: lsr_frontiers.F2_CIRCUIT_THRESHOLD,
    "f3VixHardBlock": lambda: config.VIX_CRIT,
    "f3AtrMultiplier": lambda: lsr_frontiers.F3_ATR_MULTIPLIER,
    "f5DefaultBlackoutBeforeMs": lambda: config.NEWS_LOCK_BEFORE_MIN * 60_000,
    "f5DefaultBlackoutAfterMs": lambda: config.NEWS_LOCK_AFTER_MIN * 60_000,
    "f7FomoWindowMs": lambda: config.LSR_SWEEP_MAX_AGE_S * 1_000,
}

#: Clé TS → motif de non-portage. Une entrée ici est une DETTE ASSUMÉE, pas un oubli : elle
#: nomme ce qui manque et ce qui la débloquera. Le test échoue si l'une d'elles finit portée
#: (registre périmé) ou si une clé du TS n'apparaît NI ici NI dans `PORTE`.
NON_PORTE: dict[str, str] = {
    "f6CooldownMs":
        "F6 — cooldown après 2 pertes consécutives. Exige un LsrRuntimeState (historique de "
        "trades) qui doit être une PROJECTION du Decision Log (§2.5), pas un champ mutable.",
    "f6ConsecutiveLossTrigger":
        "F6 — idem : le compteur de pertes consécutives est une projection, pas une variable.",
    "f7ResubmitLockoutMs":
        "F7-resubmit — verrou de 15 min sur un setup déjà rejeté. Exige `rejectedSetupIds` + "
        "`lockoutUntil` (état runtime). Le Python borne la fréquence autrement "
        "(LSR_REARM_COOLDOWN_S, une émission max par fenêtre) : ce n'est PAS la même règle.",
    "f8RestrictedThreshold":
        "F8 — mode restreint à 60 % de drawdown de campagne. Exige `campaign_floor` sur "
        "AccountState + le compteur `trades_today`.",
    "f8StopThreshold": "F8 — arrêt de campagne à 80 %. Même dépendance que ci-dessus.",
    "f8StopDurationMs": "F8 — durée de l'arrêt de campagne (24 h). Exige `campaignStopUntil`.",
    "f8RestrictedMaxTradesPerDay":
        "F8 — plafond de 3 trades/jour en mode restreint. Exige `trades_today`.",
    "normalMaxTradesPerDay":
        "F8 — plafond de 10 trades/jour en mode normal. Exige `trades_today`.",
    "clip1Ratio":
        "Scale-out — le plan d'exécution Python ne porte pas encore de découpe en deux clips. "
        "Règle PURE et courte, sans dépendance : prochaine tranche.",
}


def test_les_constantes_globales_portees_sont_IDENTIQUES(ts):
    defauts = _bloc(ts, "DEFAULT_CONFIG")
    ecarts = []
    for cle, lire in PORTE.items():
        if cle not in defauts:
            ecarts.append(f"{cle} : plus présente dans DEFAULT_CONFIG — le port pointe dans le vide")
            continue
        obtenu = float(lire())               # type: ignore[operator]
        if obtenu != defauts[cle]:
            ecarts.append(f"{cle} : TS={defauts[cle]} · Python={obtenu}")
    assert ecarts == [], "\n".join(ecarts)


def test_AUCUNE_constante_TS_ne_peut_etre_IGNOREE(ts):
    """LA propriété du verrou. Une clé neuve côté TypeScript fait tomber ce test tant que
    personne n'a décidé de son sort — portée (dans `PORTE`) ou assumée non portée (dans
    `NON_PORTE`, avec un motif). Sans ça, une règle pourrait apparaître dans le moteur de
    référence et n'exister dans Cholismo pour personne."""
    defauts = set(_bloc(ts, "DEFAULT_CONFIG"))
    orphelines = sorted(defauts - set(PORTE) - set(NON_PORTE))
    assert orphelines == [], (
        f"constantes de DEFAULT_CONFIG dont le sort n'est PAS tranché : {orphelines}. "
        "Les porter (→ PORTE) ou assumer leur absence (→ NON_PORTE, avec un motif).")


def test_le_registre_des_NON_PORTEES_ne_POURRIT_pas(ts):
    """Une dette remboursée doit sortir du registre. Sinon il devient un catalogue de choses
    fausses que plus personne ne relit — et le prochain qui le lira croira ces règles absentes."""
    defauts = set(_bloc(ts, "DEFAULT_CONFIG"))
    fantomes = sorted(set(NON_PORTE) - defauts)
    assert fantomes == [], (
        f"entrées de NON_PORTE qui ne correspondent à RIEN dans config.ts : {fantomes}")
    doublons = sorted(set(NON_PORTE) & set(PORTE))
    assert doublons == [], f"clés à la fois portées ET déclarées non portées : {doublons}"
    assert all(motif.strip() for motif in NON_PORTE.values()), "un motif vide n'est pas un motif"


# --- 3. Preset de compte -----------------------------------------------------------------------

def test_le_preset_APEX_50K_est_IDENTIQUE(ts):
    """Ces montants ont une valeur MONÉTAIRE directe : depuis mars 2026 Apex ne propose plus de
    reset, donc un breach impose le rachat d'une évaluation. Les avoir différents des deux côtés
    voudrait dire que le moteur de référence et Cholismo ne dimensionnent pas le même compte."""
    preset = _bloc(ts, "APEX_EOD_50K")
    assert preset["initialCapital"] == APEX_EOD_50K.initial_capital
    assert preset["maxDrawdown"] == APEX_EOD_50K.max_drawdown
    assert preset["dailyLossLimit"] == APEX_EOD_50K.daily_loss_limit
    assert preset["profitTarget"] == APEX_EOD_50K.profit_target


# --- 4. Le multiplicateur VIX, qui n'est pas une constante mais une FONCTION -------------------

def test_les_paliers_VIX_du_TS_sont_ceux_du_Python(ts):
    """`vixMultiplier` est du code, pas un littéral : on lit ses seuils dans le corps de la
    fonction et on vérifie que la fonction Python bascule aux MÊMES endroits. C'est la borne de
    20.00 (exclusive, D-070) qui se joue ici — celle qui divergeait vraiment."""
    corps = ts[ts.index("export function vixMultiplier"):]
    corps = corps[:corps.index("\n}")]
    seuils = [float(x) for x in re.findall(r"vix\s*<\s*([0-9.]+)", corps)]
    assert seuils == [15, 20], f"paliers lus dans le TS : {seuils} — le verrou ne les reconnaît plus"
    rendus = [float(x) for x in re.findall(r"return\s+([0-9.]+)", corps)]
    assert rendus == [0, 1.0, 0.75, 0.5], f"valeurs lues dans le TS : {rendus}"
    # …et le Python bascule aux mêmes endroits, bornes comprises.
    for vix, attendu in ((14.999, 1.0), (15.0, 0.75), (19.999, 0.75), (20.0, 0.5), (30.0, 0.5)):
        assert lsr_tuning.vix_multiplier(vix) == attendu, vix
