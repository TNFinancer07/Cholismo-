"""La couture microstructure live (D-097).

Ce qui est testé n'est pas « ça marche » — aucun fournisseur n'est joignable — mais les
propriétés qui doivent tenir LE JOUR où un client réel arrive : fail-closed sans repli,
estampillage honnête, et refus des incohérences d'identité.
"""
from __future__ import annotations

import asyncio

import pytest

from app.datasource.live import CLIENTS, LiveDataSource, MicrostructureClient, resolve_client
from app.datasource.mock import MOCK_PREFIX


class _Client:
    def __init__(self, vendor: str = "rithmic", *, connected: bool = True,
                 prints=None, book=None, boom: bool = False) -> None:
        self._vendor, self._connected = vendor, connected
        self._prints, self._book, self._boom = prints or [], book, boom
        self.closed = False

    @property
    def vendor(self) -> str:
        return self._vendor

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self.closed = True

    def drain_prints(self):
        if self._boom:
            raise RuntimeError("socket morte")
        out, self._prints = self._prints, []
        return out

    def order_book(self):
        if self._boom:
            raise RuntimeError("socket morte")
        return self._book


class _State:
    def __init__(self, up: bool = True) -> None:
        self.writes: list[dict] = []
        self._up = up

    async def source_up(self, source: str) -> bool:
        return self._up

    async def write_raw(self, field, value, source, ts=None, flags=None) -> None:
        self.writes.append({"field": field, "value": value, "source": source, "ts": ts})


def _tick(ds: LiveDataSource, state: _State) -> None:
    asyncio.run(ds.tick_fast(state))


# ---------------------------------------------------------------- identité

def test_le_registre_de_connecteurs_est_VIDE_et_c_est_la_verite():
    """Une entrée ici signifierait « ce fournisseur est joignable ». Aucun ne l'est."""
    assert CLIENTS == {}
    assert resolve_client("rithmic") is None
    assert resolve_client("nimporte_quoi") is None


def test_un_client_REEL_ne_peut_pas_s_estampiller_mock():
    """Le préfixe est réservé aux lectures simulées (D-093). L'inverse aussi doit être verrouillé,
    sinon un client pourrait se déguiser en mock — ou pire, un mock en client."""
    with pytest.raises(ValueError, match="réservé"):
        LiveDataSource(_Client(vendor=f"{MOCK_PREFIX}rithmic"), source_name=f"{MOCK_PREFIX}rithmic")


def test_un_client_SANS_nom_est_refuse():
    with pytest.raises(ValueError, match="sans nom"):
        LiveDataSource(_Client(vendor=""), source_name="")


def test_une_identite_INCOHERENTE_est_refusee_au_demarrage():
    """Si le client dit « bookmap » et la config « rithmic », `/sources` et la table de provenance
    nommeraient une source que personne n'écrit : la coupure ne couperait rien."""
    with pytest.raises(ValueError, match="incohérente"):
        LiveDataSource(_Client(vendor="bookmap"), source_name="rithmic")


# ---------------------------------------------------------------- fail-closed

def test_un_client_DECONNECTE_n_ecrit_RIEN():
    """Le silence est la bonne réponse parce qu'il est visible : l'âge court, le champ passe
    STALE puis ABSENT. Écrire une dernière valeur connue rendrait la panne invisible."""
    ds = LiveDataSource(_Client(connected=False, prints=[{"ts": 1.0, "price": 5000, "size": 2}]),
                        source_name="rithmic")
    state = _State()
    _tick(ds, state)
    assert state.writes == []


def test_un_client_qui_LEVE_n_ecrit_RIEN_et_ne_propage_pas():
    ds = LiveDataSource(_Client(boom=True), source_name="rithmic")
    state = _State()
    _tick(ds, state)                                   # ne doit pas lever
    assert state.writes == []


def test_une_source_COUPEE_n_ecrit_rien():
    ds = LiveDataSource(_Client(prints=[{"ts": 1.0, "price": 5000, "size": 2}]),
                        source_name="rithmic")
    _tick(ds, state := _State(up=False))
    assert state.writes == []


def test_AUCUN_repli_sur_le_mock():
    """La tentation évidente et interdite : un flux mort ne doit jamais être remplacé par des
    valeurs simulées. On vérifie qu'aucune écriture ne porte la marque du mock."""
    ds = LiveDataSource(_Client(connected=False), source_name="rithmic")
    _tick(ds, state := _State())
    assert not [w for w in state.writes if str(w["source"]).startswith(MOCK_PREFIX)]
    assert state.writes == []


# ---------------------------------------------------------------- publication

def test_les_lectures_portent_le_VRAI_nom_du_fournisseur():
    ds = LiveDataSource(_Client(prints=[{"ts": 10.0, "price": 5000.25, "size": 3, "side": "BUY"}],
                                book={"bids": [[4999.75, 12]], "asks": [[5000.25, 8]]}),
                        source_name="rithmic")
    _tick(ds, state := _State())

    assert {w["field"] for w in state.writes} == {"tape", "order_book"}
    assert all(w["source"] == "rithmic" for w in state.writes)
    assert not any(str(w["source"]).startswith(MOCK_PREFIX) for w in state.writes)


def test_un_tick_SANS_print_neuf_ne_republie_PAS_le_tape():
    """Le piège : republier le tape à l'identique avec un horodatage neuf ferait passer un flux
    mort pour un flux calme. Un tape immobile doit RESTER immobile."""
    client = _Client(prints=[{"ts": 10.0, "price": 5000, "size": 1}])
    ds = LiveDataSource(client, source_name="rithmic")

    _tick(ds, state := _State())
    assert [w["field"] for w in state.writes] == ["tape"]

    _tick(ds, state2 := _State())                      # le client a été drainé : plus rien
    assert [w["field"] for w in state2.writes] == []


def test_un_print_INCOMPLET_est_ecarte_et_non_comble():
    ds = LiveDataSource(_Client(prints=[{"ts": 1.0, "price": 5000},            # pas de size
                                        {"price": 5000, "size": 2},           # pas de ts
                                        {"ts": 3.0, "price": 5001, "size": 4}]),
                        source_name="rithmic")
    _tick(ds, state := _State())

    tape = [w for w in state.writes if w["field"] == "tape"][0]["value"]
    assert len(tape) == 1 and tape[0]["price"] == 5001


def test_un_carnet_VIDE_n_est_pas_publie():
    """Un carnet à zéro niveau se lirait « plus aucune liquidité » — c'est une mesure, et elle
    serait fausse. `None` et `{}` valent tous deux « inconnu »."""
    for book in (None, {}):
        ds = LiveDataSource(_Client(book=book), source_name="rithmic")
        _tick(ds, state := _State())
        assert not [w for w in state.writes if w["field"] == "order_book"], book


def test_le_carnet_est_date_de_MAINTENANT_pas_du_dernier_print():
    """Un marché sans transaction a quand même un carnet vivant : le dater d'un print ancien le
    ferait vieillir à tort vers STALE."""
    import time
    ds = LiveDataSource(_Client(prints=[{"ts": 1.0, "price": 5000, "size": 1}],
                                book={"bids": [[4999, 5]], "asks": [[5001, 5]]}),
                        source_name="rithmic")
    _tick(ds, state := _State())

    book_w = [w for w in state.writes if w["field"] == "order_book"][0]
    tape_w = [w for w in state.writes if w["field"] == "tape"][0]
    assert tape_w["ts"] == 1.0, "le tape garde l'horodatage du print"
    assert book_w["ts"] > time.time() - 5, "le carnet est daté de maintenant"


def test_le_tape_est_BORNE():
    ds = LiveDataSource(_Client(prints=[{"ts": float(k), "price": 5000, "size": 1}
                                        for k in range(50)]),
                        source_name="rithmic", tape_maxlen=10)
    _tick(ds, state := _State())
    tape = [w for w in state.writes if w["field"] == "tape"][0]["value"]
    assert len(tape) == 10 and tape[-1]["ts"] == 49.0


def test_la_macro_n_est_JAMAIS_inventee_par_un_flux_de_microstructure():
    ds = LiveDataSource(_Client(), source_name="rithmic")
    asyncio.run(ds.tick_slow(state := _State()))
    assert state.writes == []


def test_le_client_de_test_satisfait_le_Protocol():
    """Sinon les tests ci-dessus prouveraient la conformité d'un objet qui n'est pas un client."""
    assert isinstance(_Client(), MicrostructureClient)
