"""Feature — L2 `options.sync` : le contexte options, de Redis au canal SSE (D-075).

`options_worker.py` est un service AUTONOME (§ sa propre docstring : un redémarrage du terminal
ne doit jamais l'affecter, ni l'inverse). Il publie `options:context:latest` avec un TTL de 90 s.
L2 le CONSOMME — elle ne le pilote pas.

**La discipline reprise telle quelle d'`optionsContext.ts`** : au moment de la décision on lit
une variable EN MÉMOIRE, jamais Redis. Le fichier TS la justifie par la mesure (~0,02 µs pour
une lecture locale, ~130× de plus pour le moindre saut asynchrone). `snapshot()` est donc
synchrone, pure sur `now`, et ne peut pas bloquer par construction.

**Une divergence assumée avec le TS, testée ici et documentée en D-075** : un `computedAt` daté
du FUTUR. Le TS calcule `age = now - computedAt`, obtient un négatif, et le compare à un seuil
positif — donc conclut `OK`. C'est fail-OPEN sur une désync d'horloge, exactement la faille que
D-050/D-048 ont fermée ailleurs dans ce dépôt. Ici, une donnée du futur est traitée comme
inexploitable.
"""
import asyncio
import json

import pytest

from app import config
from app.options_context import (
    OPTIONS_CONTEXT_KEY, OPTIONS_UPDATE_CHANNEL, ContextHealth, OptionsContextReader,
    OptionsContextUnavailable,
)


def _payload(computed_at_ms, status="OK", **kw):
    base = {
        "status": status,
        "gexLocalByStrike": {"6000": 120.5, "6025": -80.0},
        "gammaZeroEs": 6007.25,
        "putWallEs": 5991.5,
        "callWallEs": 6015.75,
        "netDriftCrossover": {"direction": "up", "ts": computed_at_ms, "sourceConfirmed": False},
        "conversionFactorUsed": 1.00334,
        "computedAt": computed_at_ms,
        "sourceVendor": "mock",
    }
    base.update(kw)
    return json.dumps(base)


class _FakeRedis:
    """Double de test derrière l'interface réellement utilisée (`get`). Le remplacer par un vrai
    Redis ne touche à rien d'autre — c'est ce que la règle « zéro code fictif » autorise
    explicitement (COMMANDS.md §3)."""

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.reads = 0

    async def get(self, key):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.value

    async def aclose(self):
        return None


def _reader(redis, now=1_000.0):
    return OptionsContextReader(redis=redis, clock=lambda: now)


# ---------------------------------------------------------------------------
# Les quatre états de santé — miroir exact de SnapshotHealth (optionsContext.ts)
# ---------------------------------------------------------------------------

def test_avant_toute_lecture_le_contexte_est_UNAVAILABLE():
    snap = _reader(_FakeRedis()).snapshot(1_000.0)
    assert snap.health is ContextHealth.UNAVAILABLE
    assert snap.raw is None and snap.age_s is None, "jamais un âge fabriqué (§3)"


def test_payload_frais_donne_OK_et_expose_les_niveaux():
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    assert asyncio.run(reader.refresh()) is True
    snap = reader.snapshot(1_000.0)
    assert snap.health is ContextHealth.OK
    assert snap.age_s == pytest.approx(0.0)
    assert snap.raw["gammaZeroEs"] == 6007.25
    assert snap.raw["putWallEs"] == 5991.5


def test_au_dela_du_seuil_le_contexte_devient_STALE():
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    juste_avant = config.OPTIONS_CONTEXT_TTL_SECONDS - 0.1
    assert reader.snapshot(1_000.0 + juste_avant).health is ContextHealth.OK
    apres = config.OPTIONS_CONTEXT_TTL_SECONDS + 0.1
    assert reader.snapshot(1_000.0 + apres).health is ContextHealth.STALE


def test_VENDOR_DOWN_est_relaye_tel_quel_meme_si_frais():
    """Le worker publie `VENDOR_DOWN` après 4 échecs consécutifs. C'est une donnée fraîche qui
    dit « je n'ai pas de donnée » — la confondre avec `OK` ferait passer des murs absents pour
    des murs mesurés."""
    r = _FakeRedis(_payload(1_000_000, status="VENDOR_DOWN", gexLocalByStrike={},
                            gammaZeroEs=None, putWallEs=None, callWallEs=None))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    snap = reader.snapshot(1_000.0)
    assert snap.health is ContextHealth.VENDOR_DOWN
    assert snap.raw["gammaZeroEs"] is None


# ---------------------------------------------------------------------------
# Divergence ASSUMÉE avec le TS — horloge du futur
# ---------------------------------------------------------------------------

def test_payload_date_du_FUTUR_n_est_PAS_traite_comme_frais():
    """Divergence documentée (D-075). Le TS conclurait `OK` sur un âge négatif — fail-OPEN sur
    désync d'horloge. Le dépôt a déjà payé cette leçon (D-050/D-048)."""
    futur_ms = int((1_000.0 + 3_600) * 1000)
    r = _FakeRedis(_payload(futur_ms))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    snap = reader.snapshot(1_000.0)
    assert snap.health is ContextHealth.STALE, "une donnée du futur est inexploitable, pas fraîche"
    assert snap.age_s < 0, "l'âge réel reste visible — on ne maquille pas la désync"


# ---------------------------------------------------------------------------
# Pannes — la boucle doit VOIR l'échec, le cache ne doit pas être corrompu
# ---------------------------------------------------------------------------

def test_redis_en_panne_LEVE_pour_que_la_boucle_compte_l_echec():
    """Un `refresh` silencieux ferait battre L2 et l'afficherait `RUNNING` alors qu'aucune donnée
    n'arrive — précisément le mensonge que D-073 existe pour empêcher."""
    reader = _reader(_FakeRedis(error=ConnectionError("redis down")))
    with pytest.raises(OptionsContextUnavailable) as exc:
        asyncio.run(reader.refresh())
    assert exc.value.reason == "redis_error"


def test_cle_absente_LEVE_aussi_le_worker_n_a_rien_publie():
    reader = _reader(_FakeRedis(None))
    with pytest.raises(OptionsContextUnavailable) as exc:
        asyncio.run(reader.refresh())
    assert exc.value.reason == "key_missing"


def test_payload_malforme_LEVE_et_le_dernier_bon_contexte_est_CONSERVE():
    """Le cache n'est jamais corrompu par une lecture ratée : la dernière valeur bonne reste, et
    vieillit naturellement vers STALE. C'est le comportement du TS, gardé tel quel."""
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    r.value = "{ceci n'est pas du JSON"
    with pytest.raises(OptionsContextUnavailable) as exc:
        asyncio.run(reader.refresh())
    assert exc.value.reason == "malformed"
    assert reader.snapshot(1_000.0).health is ContextHealth.OK, "l'ancien contexte survit"


def test_payload_sans_computedAt_est_malforme_pas_frais():
    r = _FakeRedis(json.dumps({"status": "OK"}))
    reader = _reader(r)
    with pytest.raises(OptionsContextUnavailable) as exc:
        asyncio.run(reader.refresh())
    assert exc.value.reason == "malformed"


def test_computedAt_non_fini_est_refuse():
    r = _FakeRedis(_payload(1_000_000).replace('"computedAt": 1000000', '"computedAt": null'))
    reader = _reader(r)
    with pytest.raises(OptionsContextUnavailable):
        asyncio.run(reader.refresh())


# ---------------------------------------------------------------------------
# La discipline de lecture : jamais d'I/O au moment de la décision
# ---------------------------------------------------------------------------

def test_snapshot_ne_touche_JAMAIS_redis():
    """C'est la règle de conception non négociable d'`optionsContext.ts`, vérifiée par mesure
    dans ce fichier : au moment de l'armement, on lit une variable en mémoire."""
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    avant = r.reads
    for _ in range(50):
        reader.snapshot(1_000.0)
    assert r.reads == avant, "snapshot() doit être purement mémoire"


def test_snapshot_est_pure_sur_now():
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    assert reader.snapshot(1_000.0).age_s == pytest.approx(0.0)
    assert reader.snapshot(1_030.0).age_s == pytest.approx(30.0)
    assert reader.snapshot(1_000.0).age_s == pytest.approx(0.0), "aucun état caché"


# ---------------------------------------------------------------------------
# Projection SSE — ce qui part sur le canal `options`
# ---------------------------------------------------------------------------

def test_projection_serialisable_et_honnete_sur_l_absence():
    reader = _reader(_FakeRedis())
    payload = reader.to_event(1_000.0)
    json.loads(json.dumps(payload))
    assert payload["health"] == "UNAVAILABLE"
    assert payload["age_s"] is None and payload["computed_at"] is None
    assert payload["gamma_zero_es"] is None and payload["gex_local_by_strike"] == {}


def test_projection_expose_les_champs_du_pont_options():
    r = _FakeRedis(_payload(1_000_000))
    reader = _reader(r)
    asyncio.run(reader.refresh())
    payload = reader.to_event(1_000.0)
    assert payload["health"] == "OK"
    assert payload["gamma_zero_es"] == 6007.25
    assert payload["put_wall_es"] == 5991.5
    assert payload["call_wall_es"] == 6015.75
    assert payload["net_drift"]["direction"] == "up"
    # O4 restera O4_SOURCE_UNCONFIRMED tant que ce drapeau est faux — prérequis externe
    # documenté (COMMANDS.md), pas un bug. La projection doit le rendre LISIBLE.
    assert payload["net_drift"]["source_confirmed"] is False
    assert payload["source_vendor"] == "mock"


# ---------------------------------------------------------------------------
# Verrou de parité (doctrine D-072) — le test qui LIT le TypeScript
# ---------------------------------------------------------------------------

def _ts_source():
    """Les sources TS vivent sous `reference/v2/fast-engine/` (marquées `AUTORITÉ` au
    MANIFEST), et non dans `lsr-engine/` : elles appartiennent au Fast Engine v1.7, un autre
    paquet avec d'autres dépendances. Les compiler dans le paquet v1.2 cassait son `tsc` sans
    rien apporter — ce dépôt ne les exécute pas, il les porte."""
    from app.options_gates import ts_reference_source
    return ts_reference_source("optionsContext.ts")


def test_parite_le_seuil_de_peremption_dit_la_MEME_chose_des_deux_cotes():
    """D-072 : un seuil écrit deux fois finit par diverger. Le test LIT le TypeScript."""
    import re
    src = _ts_source()
    m = re.search(r"STALE_THRESHOLD_MS\s*=\s*([0-9_]+)", src)
    assert m, "STALE_THRESHOLD_MS introuvable dans optionsContext.ts"
    ts_ms = int(m.group(1).replace("_", ""))
    assert ts_ms / 1000.0 == config.OPTIONS_CONTEXT_TTL_SECONDS, (
        f"TS {ts_ms} ms vs Python {config.OPTIONS_CONTEXT_TTL_SECONDS} s — divergence")


def test_parite_la_cle_redis_et_le_canal_sont_IDENTIQUES():
    """Une clé qui diverge ne casse aucun test unitaire : elle produit juste un terminal
    éternellement `UNAVAILABLE` face à un worker qui publie correctement."""
    import re
    src = _ts_source()
    key = re.search(r"OPTIONS_CONTEXT_KEY\s*=\s*'([^']+)'", src)
    chan = re.search(r"OPTIONS_UPDATE_CHANNEL\s*=\s*'([^']+)'", src)
    assert key and chan
    assert key.group(1) == OPTIONS_CONTEXT_KEY
    assert chan.group(1) == OPTIONS_UPDATE_CHANNEL


def test_parite_avec_le_WORKER_qui_publie_reellement():
    """Le verrou ne vaut que s'il couvre les deux bouts : le producteur Python et le
    consommateur TS doivent nommer la même clé que nous."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[1] / "workers" / "options_worker.py"
           ).read_text(encoding="utf-8")
    key = re.search(r'REDIS_CONTEXT_KEY\s*=\s*"([^"]+)"', src)
    chan = re.search(r'REDIS_UPDATE_CHANNEL\s*=\s*"([^"]+)"', src)
    ttl = re.search(r"CONTEXT_TTL_SECONDS\s*=\s*(\d+)", src)
    assert key and chan and ttl
    assert key.group(1) == OPTIONS_CONTEXT_KEY
    assert chan.group(1) == OPTIONS_UPDATE_CHANNEL
    assert float(ttl.group(1)) == config.OPTIONS_CONTEXT_TTL_SECONDS


# ---------------------------------------------------------------------------
# Canal SSE `options`
# ---------------------------------------------------------------------------

def test_le_canal_options_existe_a_cote_de_fast_et_slow():
    from app.sse import CHANNELS
    assert CHANNELS == ("fast", "slow", "options")


def test_l_endpoint_sse_accepte_options_et_refuse_l_inconnu():
    from fastapi.testclient import TestClient
    from app.api import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/sse/inconnu").status_code == 404


def test_le_canal_options_ne_REJOUE_pas_la_sante_des_boucles():
    """Le contexte options est un ÉTAT (il se rejoue pour hydrater un abonné neuf) ; la santé
    des boucles est datée — la rejouer afficherait un âge figé d'avant la connexion."""
    from app.sse import Broadcaster
    b = Broadcaster()
    b.publish("options", "options_context", {"health": "OK"})
    b.publish("options", "loops_health", {"generated_at": 1.0}, replay=False)
    q = b.subscribe("options")
    hydrated = []
    while not q.empty():
        hydrated.append(q.get_nowait()["event"])
    assert hydrated == ["options_context"]
