"""Export Notion — le mappage (D-118).

Ce qui est testé est ce qui peut être faux hors réseau : la transformation. Et la règle qui
décide de la valeur du jeu exporté — **absent n'est pas zéro**, ici aussi.
"""
from __future__ import annotations

from app.notion_export import (
    already_exported,
    is_configured,
    to_notion_properties,
)

ENTREE = {
    "setup_id": "MES:BID_SWEEP:1786714200",
    "ts_ms": 1786714200000.0,
    "instrument": "MES",
    "side": "BUY",
    "gates": {"b1": {"verdict_inhouse": True}, "b2": {"verdict_inhouse": False}},
    "feature_vector": {
        "features": {"instrument": "MES", "direction": "BUY", "tp_target_ticks": 5.0,
                     "stop_loss_ticks": 4.0, "rr_ratio": 1.25, "distance_to_vpoc_ticks": 8.0,
                     "cvd": -1450.0, "aggressor_ratio": 0.66},
        "missing": ["vix"],
    },
}


# ---------------------------------------------------------------- opt-in

def test_l_export_est_OPT_IN_STRICT():
    """Un export qui s'activerait tout seul enverrait des données de trading vers un service
    tiers sans que personne l'ait demandé."""
    assert is_configured("cle", "base") is True
    assert is_configured("cle", None) is False
    assert is_configured(None, "base") is False
    assert is_configured("", "") is False
    assert is_configured("   ", "base") is False


# ---------------------------------------------------------------- absent ≠ zéro

def test_un_champ_ABSENT_est_OMIS_jamais_ecrit_a_zero():
    """Une propriété `number` à 0 dans Notion serait indiscernable d'une mesure nulle, et
    corromprait le même jeu que D-108 protège en amont."""
    entree = {**ENTREE, "feature_vector": {"features": {"rr_ratio": None, "cvd": None},
                                           "missing": ["rr_ratio", "cvd"]}}
    props = to_notion_properties(entree)
    assert "R:R" not in props
    assert "OF3" not in props
    assert 0 not in [p.get("number") for p in props.values() if isinstance(p, dict)]


def test_un_ZERO_REEL_est_bien_EXPORTE():
    """Le pendant : omettre un vrai zéro effacerait une mesure."""
    entree = {**ENTREE, "feature_vector": {"features": {"cvd": 0.0}, "missing": []}}
    props = to_notion_properties(entree)
    assert props["OF3"] == {"number": 0.0}


def test_la_ligne_DIT_ce_qui_n_a_pas_ete_mesure():
    """Une ligne muette laisserait croire à un relevé complet."""
    props = to_notion_properties(ENTREE)
    assert "vix" in props["Non mesuré"]["rich_text"][0]["text"]["content"]


def test_sans_rien_de_manquant_la_colonne_est_OMISE():
    entree = {**ENTREE, "feature_vector": {**ENTREE["feature_vector"], "missing": []}}
    assert "Non mesuré" not in to_notion_properties(entree)


# ---------------------------------------------------------------- gates

def test_les_verdicts_de_gate_sont_traduits_en_clair():
    props = to_notion_properties(ENTREE)
    assert props["OF1"] == {"select": {"name": "franchie"}}
    assert props["OF2"] == {"select": {"name": "refusée"}}


def test_une_gate_NON_MESURABLE_est_omise_pas_marquee_refusee():
    """L'écrire « refusée » ferait apprendre au modèle qu'une absence de mesure prédit un refus."""
    entree = {**ENTREE, "gates": {"b1": {"verdict_inhouse": None}, "b2": {}}}
    props = to_notion_properties(entree)
    assert "OF1" not in props and "OF2" not in props


def test_des_gates_ABSENTES_ne_font_pas_echouer_la_ligne():
    props = to_notion_properties({**ENTREE, "gates": None})
    assert props is not None and "Setup" in props


# ---------------------------------------------------------------- robustesse

def test_une_entree_SANS_identifiant_n_est_pas_exportee():
    """Une ligne irrattachable ne vaut rien — et polluerait la base."""
    assert to_notion_properties({**ENTREE, "setup_id": None}) is None
    assert to_notion_properties({}) is None


def test_une_entree_ILLISIBLE_rend_None_sans_lever():
    """Un export est un confort : il ne doit pas pouvoir casser la boucle qui l'appelle."""
    for mauvais in (None, 42, "entrée", []):
        assert to_notion_properties(mauvais) is None


def test_le_titre_existe_TOUJOURS_car_Notion_l_exige():
    props = to_notion_properties(ENTREE)
    assert props["Setup"]["title"][0]["text"]["content"].startswith("MES:")


# ---------------------------------------------------------------- anti-doublon

def test_un_setup_deja_exporte_ne_repart_PAS():
    """Le journal est append-only et relu en entier : sans cette garde, chaque redémarrage
    recréerait toutes les lignes déjà envoyées."""
    assert already_exported("s1", {"s1", "s2"}) is True
    assert already_exported("s3", {"s1", "s2"}) is False
    assert already_exported(None, set()) is True, "rien à exporter = déjà fait"


# ---------------------------------------------------------------- worker (D-118)

def _worker(monkeypatch, tmp_path):
    import importlib
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "workers"))
    monkeypatch.setenv("NOTION_STATE_PATH", str(tmp_path / "exported.json"))
    mod = importlib.import_module("notion_exporter")
    importlib.reload(mod)
    return mod


class _Reponse:
    def __init__(self, code=200, text=""):
        self.status_code, self.text = code, text


class _Client:
    def __init__(self, comportement=None):
        self.appels: list[dict] = []
        self._c = comportement or (lambda: _Reponse())

    async def post(self, url, **kw):
        self.appels.append(kw)
        r = self._c()
        if isinstance(r, Exception):
            raise r
        return r


def test_une_COUPURE_reseau_ne_leve_pas_et_la_ligne_repartira(monkeypatch, tmp_path):
    import asyncio
    m = _worker(monkeypatch, tmp_path)
    client = _Client(lambda: ConnectionError("réseau coupé"))
    ok = asyncio.run(m.envoyer(client, {"Setup": {}}, "base", "cle"))
    assert ok is False, "un échec ne doit pas être compté comme un envoi"


def test_une_CLE_INVALIDE_est_journalisee_pas_levee(monkeypatch, tmp_path):
    import asyncio
    m = _worker(monkeypatch, tmp_path)
    client = _Client(lambda: _Reponse(401, '{"message":"API token is invalid"}'))
    assert asyncio.run(m.envoyer(client, {"Setup": {}}, "base", "cle")) is False


def test_un_etat_ILLISIBLE_donne_un_ensemble_VIDE(monkeypatch, tmp_path):
    """On préfère un doublon visible dans Notion à un trou silencieux dans l'historique."""
    m = _worker(monkeypatch, tmp_path)
    (tmp_path / "exported.json").write_text("pas du json", encoding="utf-8")
    assert m.charger_exportes() == set()


def test_l_etat_persiste_entre_deux_passes(monkeypatch, tmp_path):
    m = _worker(monkeypatch, tmp_path)
    m.enregistrer_exportes({"s1", "s2"})
    assert m.charger_exportes() == {"s1", "s2"}


def test_un_journal_ILLISIBLE_abandonne_la_passe_sans_rien_perdre(monkeypatch, tmp_path):
    import asyncio
    m = _worker(monkeypatch, tmp_path)

    class _JournalCasse:
        def projection(self):
            raise RuntimeError("base verrouillée")

    monkeypatch.setattr(m, "SetupJournal", _JournalCasse)
    assert asyncio.run(m.passe(_Client(), "cle", "base")) == 0
