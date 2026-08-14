"""Pont Stream Deck (D-119).

Une touche se lit d'un coup d'œil, sans infobulle pour nuancer. Ce qui est testé, c'est qu'elle ne
puisse jamais affirmer plus que ce qui est mesuré — et qu'aucune touche ne décide.
"""
from __future__ import annotations

import pathlib

from app.streamdeck import ACTIONS, REFUSED, build_keys, validate_action

ETAT = {
    "armed": True,
    "protection": {"locked": False, "lock_reason": None},
    "extras": {
        "orderflow_shadow": {"b1": {"verdict_inhouse": True, "inhouse": 0.72},
                             "b2": {"verdict_inhouse": False, "inhouse": 0.31},
                             "b3": 0.41, "b4": 1.28},
        "liquidity_vacuum": {"vacuum": False},
    },
}


def _par_cle(state):
    return {t["key"]: t for t in build_keys(state)}


# ---------------------------------------------------------------- §2.1 / §6

def test_AUCUNE_touche_ne_peut_enregistrer_un_GO():
    """Un GO exige Phase 0 OPEN et un self-check à quatre réponses. Une touche ne peut pas
    attester qu'on a dormi, qu'on est concentré, qu'on n'est pas en tilt et que le plan est
    écrit. Lui faire poster un self-check pré-rempli automatiserait le mensonge que la gate
    existe pour empêcher."""
    ok, motif = validate_action("decision_go")
    assert ok is False
    assert "self-check" in motif


def test_le_refus_est_NOMMÉ_pas_generique():
    """« action inconnue » n'est pas actionnable ; « voici pourquoi » l'est."""
    for action in ("decision_go", "decision_no_go", "place_order", "arm_setup"):
        ok, motif = validate_action(action)
        assert ok is False and motif and len(motif) > 20, action


def test_l_armement_ne_se_declenche_pas_a_la_main():
    ok, motif = validate_action("arm_setup")
    assert ok is False and "moteur déterministe" in motif


def test_la_liste_blanche_est_STRUCTURELLE():
    """Une action absente ne peut pas être exécutée — ce n'est pas une convention."""
    ok, motif = validate_action("nimporte_quoi")
    assert ok is False and "hors liste blanche" in motif
    assert set(ACTIONS) & set(REFUSED) == set(), "une action ne peut pas être à la fois permise et refusée"


def test_aucun_vocabulaire_d_ORDRE_dans_la_source():
    src = (pathlib.Path(__file__).resolve().parent.parent / "app" / "streamdeck.py") \
        .read_text(encoding="utf-8").lower()
    for interdit in ("submit_order", "placeorder", "broker", "httpx.post("):
        assert interdit not in src, interdit


def test_les_actions_autorisees_sont_toutes_REVERSIBLES():
    assert set(ACTIONS) == {"audio_toggle", "detach_panel", "set_workspace", "focus_terminal"}


def test_detach_panel_exige_son_panneau():
    assert validate_action("detach_panel")[0] is False
    assert validate_action("detach_panel", {"panel": "OFG"})[0] is True


# ---------------------------------------------------------------- affichage

def test_une_mesure_ABSENTE_n_allume_pas_une_touche_verte():
    """Une touche verte sur une mesure absente ferait ce que tout ce dépôt empêche — mais sur un
    objet qu'on regarde du coin de l'œil."""
    vide = {"extras": {"orderflow_shadow": {"b1": {"verdict_inhouse": None}},
                       "liquidity_vacuum": {"vacuum": None}}}
    t = _par_cle(vide)
    assert t["OF1"]["status"] == "UNKNOWN"
    assert t["VACUUM"]["status"] == "UNKNOWN" and t["VACUUM"]["value"] == "—"


def test_un_etat_TOTALEMENT_absent_ne_ment_pas():
    t = _par_cle({})
    assert all(x["status"] == "UNKNOWN" for x in t.values()), t


def test_le_verrou_prime_sur_l_armement_a_l_ecran():
    """Un setup armé pendant un verrou ne doit pas s'afficher « ARMÉ » : c'est le verrou qui
    décide de ce qui se passe."""
    t = _par_cle({**ETAT, "protection": {"locked": True, "lock_reason": "F6_COOLDOWN_ACTIVE"}})
    assert t["SETUP"]["value"] == "VERROUILLÉ" and t["SETUP"]["status"] == "ALERT"
    assert t["LOCK"]["status"] == "ALERT"


def test_les_gates_portent_leur_verdict_et_leur_valeur():
    t = _par_cle(ETAT)
    assert t["OF1"]["status"] == "OK" and t["OF1"]["value"] == "0.72"
    assert t["OF2"]["status"] == "ALERT"


def test_le_statut_est_un_NOM_jamais_une_couleur():
    """Le pont ne décide pas du rendu, et un boîtier monochrome doit rester lisible (§3)."""
    for t in build_keys(ETAT):
        assert t["status"] in ("OK", "WARN", "ALERT", "UNKNOWN")
        assert "#" not in str(t["status"])


def test_un_vide_de_carnet_est_un_AVERTISSEMENT_pas_une_alerte():
    t = _par_cle({**ETAT, "extras": {**ETAT["extras"], "liquidity_vacuum": {"vacuum": True}}})
    assert t["VACUUM"]["status"] == "WARN" and t["VACUUM"]["value"] == "OUI"


def test_build_keys_ne_leve_JAMAIS():
    for mauvais in (None, 42, "état", [], {"extras": "cassé"}):
        assert isinstance(build_keys(mauvais), list), mauvais


# ---------------------------------------------------------------- daemon (D-119)

def test_le_pont_n_ecoute_QUE_en_local():
    """Un boîtier est branché sur le poste. Exposer ce pont au réseau donnerait à un tiers les
    commandes d'un terminal de trading — même bornées à des actions réversibles."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "workers" / "streamdeck_bridge.py").read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in src
    # La forme LITTÉRALE d'un bind, pas la mention : le module explique justement pourquoi il ne
    # s'y lie pas, et interdire le mot empêcherait d'écrire la raison.
    assert '"0.0.0.0"' not in src and "'0.0.0.0'" not in src


def test_le_pont_est_OPT_IN():
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "workers" / "streamdeck_bridge.py").read_text(encoding="utf-8")
    assert 'STREAMDECK_BRIDGE", "") != "1"' in src


def test_le_pont_ne_fait_que_des_LECTURES_sur_l_API():
    """Un POST depuis le pont contournerait les gardes du terminal."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "workers" / "streamdeck_bridge.py").read_text(encoding="utf-8")
    assert "client.post" not in src and ".put(" not in src and ".delete(" not in src


def test_un_refus_est_RENVOYÉ_au_boitier_avec_son_motif():
    """Sinon l'opérateur appuie et ne comprend pas pourquoi rien ne se passe."""
    import asyncio
    import json
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "workers"))
    import streamdeck_bridge as m

    class _W:
        def __init__(self): self.sorties = []
        def write(self, b): self.sorties.append(b.decode())

    w = _W()
    asyncio.run(m._traiter(json.dumps({"action": "decision_go"}).encode(), w))
    rep = json.loads(w.sorties[0])
    assert rep["refused"] == "decision_go" and "self-check" in rep["reason"]


def test_une_action_AUTORISEE_est_relayee_jamais_executee_par_le_pont():
    import asyncio
    import json
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "workers"))
    import streamdeck_bridge as m

    class _W:
        def __init__(self): self.sorties = []
        def write(self, b): self.sorties.append(b.decode())

    w = _W()
    asyncio.run(m._traiter(json.dumps({"action": "audio_toggle"}).encode(), w))
    assert json.loads(w.sorties[0])["accepted"] == "audio_toggle"
