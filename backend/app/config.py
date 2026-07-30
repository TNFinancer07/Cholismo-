"""Central configuration. Every named threshold below marked AUTORITÉ comes verbatim from
PRD.md / TASKS.md / CLAUDE.md; the rest are PLACEHOLDER assumptions logged in DECISIONS.md."""
import os

# --- Cadences (CLAUDE §6 — fast/slow SSE channels; demo values, D-016) ---
FAST_TICK_SECONDS = 0.25
SLOW_TICK_SECONDS = float(os.getenv("SLOW_TICK_SECONDS", "15"))

# --- Freshness thresholds (per channel; GEX threshold is AUTORITÉ PRD §B2) ---
FAST_STALE_SECONDS = 3.0
FAST_ABSENT_SECONDS = 15.0
SLOW_STALE_SECONDS = SLOW_TICK_SECONDS * 3
SLOW_ABSENT_SECONDS = SLOW_TICK_SECONDS * 10
GEX_STALE_SECONDS = float(os.getenv("GEX_STALE_SECONDS", "180"))  # AUTORITÉ — single config

# --- Phase 0 / risk thresholds (AUTORITÉ TASKS §2.3 unless noted) ---
CHOP_CRIT = 61.8          # AUTORITÉ — CHOP >= 61.8 crit
VIX_CRIT = 30.0           # AUTORITÉ — VIX > 30 crit
RMS_WARN = 3.0            # AUTORITÉ — RMS >= 3 warn
RMS_CRIT = 5.0            # PLACEHOLDER — crit level, D-005
STREAK_AUDIT_THRESHOLD = 8  # AUTORITÉ — forced audit at 8 (PRD §C2)

# --- Decision window (PRD §C3) ---
ANTIPARALYSIS_SECONDS = float(os.getenv("ANTIPARALYSIS_SECONDS", "90"))  # AUTORITÉ (to revalidate vs S1 horizon)
DECISION_ARM_THRESHOLD = 60.0  # PLACEHOLDER — D-008

# --- Unified signal weights (AUTORITÉ PRD §0) ---
WEIGHT_STRUCTURE = 0.35
WEIGHT_ORDER_FLOW = 0.25
WEIGHT_MACRO = 0.20
WEIGHT_SENTIMENT = 0.15
WEIGHT_QUALITY = 0.05
DEGRADED_DENOMINATOR = 80.0  # AUTORITÉ — renormalize /80 when macro not calibrated

# --- Calibration / proof (AUTORITÉ CLAUDE §1/§2.7, PRD §C4) ---
CALIBRATION_WINDOW = 60          # N/60 gauge
CALIBRATION_TARGET_TRADES = 50   # 50+ disciplined trades
RESULT_SCORE_MIN_TRADES = 20     # result score displayed only after 20+
SIZING_LOCK_PCT = 50             # sizing locked at 50 %

# --- Reconciliation (PRD §Réconciliation; window/r-unit PLACEHOLDER D-018) ---
RECON_MATCH_WINDOW_SECONDS = float(os.getenv("RECON_MATCH_WINDOW_SECONDS", "120"))
R_UNIT_USD = float(os.getenv("R_UNIT_USD", "100"))

# --- Cognitive self-check (PRD §C5; TTL PLACEHOLDER) ---
SELF_CHECK_TTL_SECONDS = 3600

# --- Macro score (CLAUDE §8.1 — never calibrated by default) ---
MACRO_CALIBRATED = os.getenv("MACRO_CALIBRATED", "false").lower() == "true"

# --- Infra ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EVENT_DB_PATH = os.getenv("EVENT_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "events.db"))
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))  # D-030
ENGINE_HEARTBEAT_MAX_AGE = 5.0  # engine itself stale -> fail-closed (D-005)

# --- AI (all async, out of hot path — CLAUDE §2.8/§7) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_TIMEOUT_SECONDS = 0.1       # AUTORITÉ — < 100 ms, fail-closed
CLAUDE_SCORING_PERIOD_SECONDS = 300
GEMINI_AUDIT_EVERY_N_TRADES = 20  # AUTORITÉ

# --- Liquidity Sweep detector (LangGraph, DÉTERMINISTE, advisory async — D-028) ---
SWEEP_TICK_SECONDS = float(os.getenv("SWEEP_TICK_SECONDS", "1.0"))  # hors hot path (§2.8)
SWEEP_RECENT_MAX = 8             # longueur du feed d'alertes récentes

# --- Trade Reconciliator (analytics FIFO sur snapshots — D-033) ---
# $/point par contrat. ES/MES = AUTORITÉ (spec) ; NQ/MNQ ajoutés (valeurs CME standard).
# Instrument inconnu → P&L USD non calculé (fail-closed §3, jamais inventé). Le risque de
# référence R réutilise R_UNIT_USD (défaut 100 $) — source unique, pas de double définition.
CONTRACT_POINT_VALUE = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}

# --- Footprint + imbalances (D-037) ---
# Ratio d'imbalance diagonal = AUTORITÉ (spec : > 300 %). Tick ES = 0.25. Le reste PLACEHOLDER
# (v1 provisional — durée de bougie, plancher de volume, fenêtres, à calibrer par l'humain).
PRICE_TICK = float(os.getenv("PRICE_TICK", "0.25"))                    # grille de prix ES
FOOTPRINT_CANDLE_SECONDS = float(os.getenv("FOOTPRINT_CANDLE_SECONDS", "60"))  # v1 provisional
FOOTPRINT_CANDLES = int(os.getenv("FOOTPRINT_CANDLES", "12"))         # bougies affichées
FOOTPRINT_IMBALANCE_RATIO = float(os.getenv("FOOTPRINT_IMBALANCE_RATIO", "3.0"))   # AUTORITÉ (300 %)
FOOTPRINT_MIN_IMBALANCE_VOL = float(os.getenv("FOOTPRINT_MIN_IMBALANCE_VOL", "1"))  # plancher, v1
FOOTPRINT_MAX_PRINTS = int(os.getenv("FOOTPRINT_MAX_PRINTS", "800"))  # tampon de prints accumulés
# D-042 — bougies TICK-BASED : N prints par bougie au lieu du bucket temporel. 0 = temporel
# (défaut, comportement D-037 inchangé). PLACEHOLDER v1 provisional, à calibrer par l'humain.
FOOTPRINT_TICKS_PER_CANDLE = int(os.getenv("FOOTPRINT_TICKS_PER_CANDLE", "0"))

# --- CVD granulaire stratifié par taille d'ordre (D-038) ---
# Seuil retail/institutionnel = v1 provisional (PLACEHOLDER — pas d'AUTORITÉ dans /reference ;
# calibration owner: Sony). Bucket temporel, fenêtre de série, deadbands de divergence = v1.
CVD_SIZE_THRESHOLD = float(os.getenv("CVD_SIZE_THRESHOLD", "10"))         # ≥ seuil → institutionnel
CVD_STRAT_BUCKET_SECONDS = float(os.getenv("CVD_STRAT_BUCKET_SECONDS", "5"))   # échantillon série
CVD_STRAT_MAX_POINTS = int(os.getenv("CVD_STRAT_MAX_POINTS", "120"))     # points de série affichés
CVD_STRAT_MAX_PRINTS = int(os.getenv("CVD_STRAT_MAX_PRINTS", "4000"))    # tampon de prints accumulés
CVD_STRAT_DIV_LOOKBACK = int(os.getenv("CVD_STRAT_DIV_LOOKBACK", "12"))  # fenêtre de divergence
CVD_STRAT_DIV_MIN_PRICE = float(os.getenv("CVD_STRAT_DIV_MIN_PRICE", "0.5"))   # deadband prix (pts)
CVD_STRAT_DIV_MIN_DELTA = float(os.getenv("CVD_STRAT_DIV_MIN_DELTA", "25"))    # deadband delta (vol)

# --- Chaîne d'options (OMON) + Term Structure de volatilité (D-039) ---
# Bande ATM + eps FLAT = v1 provisional (PLACEHOLDER §11 — pas d'AUTORITÉ ; à calibrer). Bornes
# d'affichage. Ténors VIX = jours standards de la structure (CBOE).
OPTIONS_ATM_BAND = float(os.getenv("OPTIONS_ATM_BAND", "6"))          # |strike−U| ≤ bande → ATM
OPTIONS_MAX_EXPIRATIONS = int(os.getenv("OPTIONS_MAX_EXPIRATIONS", "4"))
OPTIONS_MAX_STRIKES = int(os.getenv("OPTIONS_MAX_STRIKES", "13"))    # strikes affichés par échéance
VOL_TERM_FLAT_EPS = float(os.getenv("VOL_TERM_FLAT_EPS", "0.3"))     # |Δ| ≤ eps → FLAT (points VIX)
VOL_TENORS = (("VIX9D", 9), ("VIX", 30), ("VIX3M", 93), ("VIX6M", 186))  # ténor → jours (CBOE)

# --- Volume Profile dynamique (D-041) ---
# VA 70 % = convention Market Profile (AUTORITÉ de facto). Ratio LVN + niveaux max = v1 provisional.
VP_VA_PCT = float(os.getenv("VP_VA_PCT", "0.70"))            # Value Area = 70 % du volume
VP_LVN_RATIO = float(os.getenv("VP_LVN_RATIO", "0.25"))     # creux ≤ 25 % du volume POC = LVN
VP_MAX_LEVELS = int(os.getenv("VP_MAX_LEVELS", "400"))      # niveaux de prix bornés (grille)

# --- Moteur Macro & Risk Guard (D-040) ---
# Fenêtres = v1 provisional (PLACEHOLDER §11 — à calibrer). La fenêtre blackout ±15 min autour
# d'un HIGH câble la règle Phase 0 MACRO_BLACKOUT (verrou unique §2.2).
MACRO_PAUSE_WINDOW_S = float(os.getenv("MACRO_PAUSE_WINDOW_S", "900"))   # ±15 min → EXECUTION_PAUSED
MACRO_WARN_WINDOW_S = float(os.getenv("MACRO_WARN_WINDOW_S", "1800"))    # 30 min avant → WARNING
MACRO_PAST_GRACE_S = float(os.getenv("MACRO_PAST_GRACE_S", "1800"))      # grâce d'affichage du passé
MACRO_MAX_EVENTS = int(os.getenv("MACRO_MAX_EVENTS", "20"))              # publications affichées

# --- Heatmap de liquidité (LOB, canal rapide 4 Hz — D-036) ---
# Fenêtre glissante de colonnes temporelles (une par tick rapide de 0,25 s). 60 colonnes ≈ 15 s
# d'historique. Niveaux par côté = profondeur affichée du carnet (BOOK_DEPTH).
HEATMAP_COLS = int(os.getenv("HEATMAP_COLS", "60"))       # colonnes temporelles conservées
HEATMAP_LEVELS = int(os.getenv("HEATMAP_LEVELS", "10"))   # niveaux par côté (= BOOK_DEPTH)

# --- Cortex Cognitif — bias_detector (analytique post-hoc, DÉTERMINISTE — D-035) ---
# Seuils de détection de biais. FOMO/EXEC = PLACEHOLDER (v1 provisional, à calibrer par l'humain
# sur les 50+ trades) ; la fenêtre revenge est AUTORITÉ (spec : < 3 min après une perte).
FOMO_MAX_DURATION_S = float(os.getenv("FOMO_MAX_DURATION_S", "30"))       # v1 provisional
EXEC_MAX_DURATION_S = float(os.getenv("EXEC_MAX_DURATION_S", "1800"))     # v1 provisional (30 min)
REVENGE_WINDOW_S = float(os.getenv("REVENGE_WINDOW_S", "180"))            # AUTORITÉ — < 3 min

# --- log_scraper : tailer NT8 → auto-snapshot (OBSERVATION seule §2.1 — D-031) ---
# Désactivé par défaut : aucun log NT8 en démo. Activer avec un vrai dossier NT8
# (Documents/NinjaTrader 8/log). Fail-closed si le dossier/log du jour est absent.
LOG_SCRAPER_ENABLED = os.getenv("LOG_SCRAPER_ENABLED", "false").lower() == "true"
NT8_LOG_DIR = os.getenv("NT8_LOG_DIR", "")
LOG_SCRAPER_POLL_SECONDS = float(os.getenv("LOG_SCRAPER_POLL_SECONDS", "1.0"))  # hors hot path

# --- Pricing d'options (D-044) — taux sans risque servant Black-Scholes ---
# PLACEHOLDER v1 provisional : à brancher sur une vraie courbe (OIS) le jour où elle est câblée.
# Sert l'inversion d'IV et les Grecques ; ne modifie aucun verrou (advisory, §2.1).
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", "0.045"))

# --- Session windows CET (PLACEHOLDER D-006) ---
LONDON_OBS_CET = (8, 12)      # 08:00–12:00 CET
OVERLAP_NY_CET = (14.5, 17.5)  # 14:30–17:30 CET

# --- Walk-Forward robustness engine (analyse OFFLINE sur trades réconciliés — D-043) ---
# Convention Walk-Forward Analysis (Pardo) : 70/30 IS/OOS = AUTORITÉ de facto ; seuil WFE < 0.5 =
# overfit (spec D-043). window/step/min = PLACEHOLDER (v1 provisional, à calibrer sur 50+ trades).
WF_IS_FRAC = float(os.getenv("WF_IS_FRAC", "0.70"))          # part In-Sample de chaque fenêtre
WF_WINDOW = int(os.getenv("WF_WINDOW", "0"))                 # trades/fenêtre (0 → toute la série)
WF_STEP = int(os.getenv("WF_STEP", "0"))                     # décalage (0 → = window, non chevauchant)
WF_OVERFIT_THRESHOLD = float(os.getenv("WF_OVERFIT_THRESHOLD", "0.50"))  # WFE < seuil ⇒ OVERFIT
WF_MIN_TRADES = int(os.getenv("WF_MIN_TRADES", "4"))        # plancher → INSUFFICIENT_DATA sinon

# --- Monte Carlo robustness (analyse OFFLINE, bootstrap avec remise — D-043 tranche 2) ---
# n_sims 5000–10000 (spec D-043) ; min/seed = PLACEHOLDER v1 provisional. Le seuil testé vient du
# réglage `risk.max_drawdown_r_day` (projection), pas d'un doublon ici.
MC_N_SIMS = int(os.getenv("MC_N_SIMS", "10000"))            # rééchantillonnages bootstrap
MC_MIN_TRADES = int(os.getenv("MC_MIN_TRADES", "4"))        # plancher → INSUFFICIENT_DATA sinon
MC_SEED = int(os.getenv("MC_SEED")) if os.getenv("MC_SEED") else None  # None → entropie (non répétable)
# Borne CPU n_sims×n_trades → jamais de hang de worker sur entrée énorme (n_sims réduit, reporté via
# `capped`). 2e6 ≈ < ~3 s Python pur ; garde 10000 sims tant que ≤ 200 trades (cas réel réconcilié).
MC_MAX_WORK = int(os.getenv("MC_MAX_WORK", "2000000"))

# --- LSR v1.2 — couche microstructure (D-046) ---
# Seuils v1 provisional (calibration « 1re passe » du doc LSR, à figer sur 60 trades réels).
# ISOLATION : cette couche ne lit QUE la microstructure — les frontières compte (F1/F2/F8),
# volatilité (F3) et news (F5) vivent dans d'autres couches/services, jamais ici.
LSR_INSTRUMENT = os.getenv("LSR_INSTRUMENT", "MES")         # Micro E-mini S&P 500
LSR_SWEEP_MAX_AGE_S = float(os.getenv("LSR_SWEEP_MAX_AGE_S", "90"))    # fraîcheur du déclencheur
LSR_EXTREME_WINDOW_S = float(os.getenv("LSR_EXTREME_WINDOW_S", "120"))  # fenêtre de l'extrême (A3)
LSR_ENTRY_OFFSET_TICKS = int(os.getenv("LSR_ENTRY_OFFSET_TICKS", "1"))  # A1 — sens réintégration
LSR_SL_BUFFER_TICKS = int(os.getenv("LSR_SL_BUFFER_TICKS", "2"))        # A3 — buffer bruit
LSR_TP_MIN_TICKS = int(os.getenv("LSR_TP_MIN_TICKS", "3"))              # A2 — TP plancher
LSR_TP_MAX_TICKS = int(os.getenv("LSR_TP_MAX_TICKS", "5"))              # A2 — TP plafond
LSR_TP_VPOC_MARGIN_TICKS = int(os.getenv("LSR_TP_VPOC_MARGIN_TICKS", "1"))  # A2 — marge avant VPOC
LSR_B2_FLIP = float(os.getenv("LSR_B2_FLIP", "0.60"))                   # B2 — bascule agressifs
# Doc LSR : 1 tick sur MES réel. Le mock émet un half-spread de 0.25 (spread = 2 ticks) en régime
# normal : 2 = calibration mock v1 provisional, à resserrer à 1 sur feed réel (env-overridable).
LSR_F4_MAX_SPREAD_TICKS = float(os.getenv("LSR_F4_MAX_SPREAD_TICKS", "2"))
LSR_F4_MIN_DEPTH = float(os.getenv("LSR_F4_MIN_DEPTH", "150"))          # top-3, chaque côté
# RiskSizer /5 + modif VIX = couche COMPTE (AccountState), hors D-046 → taille fixe v1.
LSR_CONTRACTS = int(os.getenv("LSR_CONTRACTS", "1"))
# F7-like — fenêtre anti-FOMO : après une émission, aucun nouveau manifeste pendant ce délai,
# quelles que soient les alertes (borne structurelle de fréquence ; doc LSR f7FomoWindowMs).
LSR_REARM_COOLDOWN_S = float(os.getenv("LSR_REARM_COOLDOWN_S", "90"))

# --- Couche Compte & RiskSizer (D-047) ---
# Règle stricte du 1/5e (doc LSR v1.1, `bufferDivisor`) : risque du prochain trade = buffer/5.
RISK_BUFFER_DIVISOR = int(os.getenv("RISK_BUFFER_DIVISOR", "5"))
# Plafond de plausibilité de taille (v1 provisional — compte cible : Apex 50K en micros ; une
# équité corrompue produirait sinon un floor() astronomique parfaitement « cohérent »).
RISK_MAX_CONTRACTS = int(os.getenv("RISK_MAX_CONTRACTS", "100"))
# Fraîcheur maximale d'une photo de compte (v1 provisional) : au-delà, l'équité est FOSSILE et
# le provider répond None — on ne dimensionne jamais sur un compte qu'on ne voit plus (§3).
ACCOUNT_MAX_AGE_S = float(os.getenv("ACCOUNT_MAX_AGE_S", "15"))
# --- NT8FileAccountProvider (D-048) : export de compte NinjaTrader ---
# Désactivé par défaut ("" = stack démo → MockAccountProvider). Activer avec le chemin du
# fichier exporté en continu par NT8 (lignes `epoch;equity[;day_start]`, un fichier/jour).
NT8_ACCOUNT_FILE = os.getenv("NT8_ACCOUNT_FILE", "")
NT8_ACCOUNT_POLL_SECONDS = float(os.getenv("NT8_ACCOUNT_POLL_SECONDS", "1.0"))

# --- MacroNewsProvider & Porte F0 (D-050) ---
# Fenêtres autour d'une publication USD à fort impact (minutes) : WARNING = [T−15, T−2),
# HARD_LOCK = [T−2, T+2] bornes incluses. Le flux ("" = désactivé, stack démo → la porte F0
# n'existe pas ; la protection de facto reste le couplage news D-028 + le blackout humain).
MACRO_NEWS_FEED_URL = os.getenv("MACRO_NEWS_FEED_URL", "")
MACRO_NEWS_REFRESH_SECONDS = float(os.getenv("MACRO_NEWS_REFRESH_SECONDS", "3600"))
# Calendrier plus vieux que ça = FOSSILE → SAFETY_UNKNOWN (on ne trade pas à l'aveugle).
MACRO_NEWS_MAX_AGE_S = float(os.getenv("MACRO_NEWS_MAX_AGE_S", "21600"))
NEWS_LOCK_BEFORE_MIN = float(os.getenv("NEWS_LOCK_BEFORE_MIN", "2"))
NEWS_LOCK_AFTER_MIN = float(os.getenv("NEWS_LOCK_AFTER_MIN", "2"))
NEWS_WARNING_BEFORE_MIN = float(os.getenv("NEWS_WARNING_BEFORE_MIN", "15"))
# Stop de RÉFÉRENCE pour le ticket pré-calculé affiché en Zone C (D-051) : l'opérateur voit sa
# capacité AVANT l'alerte. 3 ticks = géométrie LSR typique sur MES (entrée+1t, stop−2t).
RISK_REFERENCE_STOP_TICKS = int(os.getenv("RISK_REFERENCE_STOP_TICKS", "3"))

# --- LsrLiveDriver (D-052) : harnais push-driven du moteur LSR ---
# Cadence d'évaluation (le détecteur de sweep tourne à la seconde — 250 ms suffit largement).
LSR_DRIVER_POLL_SECONDS = float(os.getenv("LSR_DRIVER_POLL_SECONDS", "0.25"))
# Fraîcheur maximale d'un snapshot marché / order flow poussé : au-delà, la donnée est FOSSILE et
# aucune évaluation n'a lieu (la boucle périodique doit être fail-CLOSED, pas fail-open).
# Le compte garde sa propre doctrine (ACCOUNT_MAX_AGE_S, D-047).
LSR_DRIVER_MAX_AGE_S = float(os.getenv("LSR_DRIVER_MAX_AGE_S", "2.0"))
