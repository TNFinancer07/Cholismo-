"""Registre des séries macro — D-057 (spec API × Arbitrage + API × Dimension).

Ce que ces tests protègent, dans l'ordre d'importance :
1. **La doctrine de confiance est EXÉCUTABLE.** « C2 = ne pas coder l'identifiant en dur sans
   être passé par le catalogue du fournisseur », « C3 = ne pas commencer ». Un test, pas une note.
2. **Le registre est le miroir du pipeline qui tourne** (`strategies/youssef.py`) — poids du
   quadrant, dimensions, arbitrages. Si l'un dérive de l'autre, ça casse ici.
3. **Les pièges de source qui cassent en SILENCE** sont armés : dataflow ICP mort, échéance du
   Bund€i, code de zone AMECO.
"""
from __future__ import annotations

import pytest

from app.providers import catalog as cat

# =============================================================================================
# Doctrine de confiance — C1 / C2 / C3
# =============================================================================================


def test_aucun_identifiant_code_en_dur_sur_une_ligne_NON_confirmee():
    """La règle centrale des deux specs : un C2/C3 n'a **pas** d'identifiant dans le code. En
    écrire un « probable » serait exactement ce que les artefacts interdisent — et il aurait
    l'air d'une clé vérifiée."""
    for spec in cat.CATALOG:
        if spec.confidence is not cat.Confidence.C1:
            assert spec.identifier is None, f"{spec.key} : identifiant codé en dur en {spec.confidence.value}"


def test_toute_ligne_C1_observee_porte_un_identifiant_et_un_fournisseur():
    for spec in cat.CATALOG:
        if spec.kind is cat.Kind.OBSERVED and spec.confidence is cat.Confidence.C1:
            assert spec.identifier, f"{spec.key} : C1 sans identifiant"
            assert spec.provider is not cat.Provider.NONE, f"{spec.key} : C1 sans fournisseur"


def test_seules_les_lignes_C1_observees_sont_collectables():
    for spec in cat.CATALOG:
        blocked = cat.fetch_block_reason(spec.key)
        collectable = spec.kind is cat.Kind.OBSERVED and spec.confidence is cat.Confidence.C1
        assert (blocked is None) is collectable, f"{spec.key} : {blocked!r}"


def test_le_motif_de_blocage_dit_QUOI_FAIRE_et_pas_seulement_non():
    """Un « non » sans suite est un cul-de-sac (§Loop 5). C2 → relever au catalogue ;
    C3 → ne pas commencer ; paramètre → calibrer, pas collecter."""
    assert "catalogue" in cat.fetch_block_reason("oecd_cli").lower()
    assert "calibr" in cat.fetch_block_reason("d4_coeff").lower()
    assert "commencer" in cat.fetch_block_reason("rr_current").lower()


def test_tous_les_motifs_ont_la_MEME_FORME_pour_etre_lisibles_en_liste():
    """Vingt-deux motifs défilent d'un coup : sans étiquette de tête commune, l'œil ne trie
    plus. Chaque motif commence par sa CATÉGORIE, puis dit quoi faire."""
    tags = ("C2 — ", "C3 — ", "paramètre — ", "dérivé — ", "inconnu — ")
    for spec in cat.CATALOG:
        reason = cat.fetch_block_reason(spec.key)
        if reason is not None:
            assert reason.startswith(tags), f"{spec.key} : {reason}"


def test_une_ligne_DERIVEE_nomme_ses_INTRANTS_au_lieu_de_renvoyer_au_code():
    """« voir depends_on » renvoie à un nom de champ, pas à la réponse. Ce qu'on veut savoir,
    c'est DEPUIS QUOI la ligne se calcule."""
    reason = cat.fetch_block_reason("output_gap_us")
    assert "gdpc1" in reason and "gdppot" in reason
    assert "depends_on" not in reason


def test_les_motifs_ne_se_REPETENT_pas_eux_memes():
    """Le motif générique et la note du registre disaient deux fois la même chose."""
    for key in ("d4_coeff", "beta_phillips", "rr_current", "r_star_ez"):
        reason = cat.fetch_block_reason(key)
        assert reason.count("pas une donnée") <= 1, key
        assert " — —" not in reason and "((" not in reason and "))" not in reason, key


def test_un_CYCLE_de_dependances_est_dit_pas_une_pile_qui_deborde():
    """Personne n'en a écrit un, mais rien ne l'empêche : une `RecursionError` au premier
    import serait un blocage sans message (§Loop 5)."""
    boucle = cat.SeriesSpec("a_test", "A", cat.Kind.DERIVED, "D1", (), cat.Leg.NONE,
                            cat.Provider.NONE, None, cat.Frequency.NONE, cat.Confidence.C1,
                            "", depends_on=("b_test",))
    autre = cat.SeriesSpec("b_test", "B", cat.Kind.DERIVED, "D1", (), cat.Leg.NONE,
                           cat.Provider.NONE, None, cat.Frequency.NONE, cat.Confidence.C1,
                           "", depends_on=("a_test",))
    registre = {**cat.BY_KEY, "a_test": boucle, "b_test": autre}
    reason = cat.fetch_block_reason("a_test", registry=registre)
    assert reason is not None and "circulaire" in reason.lower()


def test_une_ligne_DERIVEE_dont_la_dependance_est_bloquee_est_bloquee_AUSSI():
    """`ilsw_ez` = nominal − réel. La jambe nominale est vérifiée, la réelle attend sa clé :
    le breakeven EUR n'existe donc pas encore, et le motif doit NOMMER le maillon manquant —
    sinon on cherche le défaut au mauvais étage."""
    reason = cat.fetch_block_reason("ilsw_ez")
    assert reason is not None and "bundei_real" in reason


def test_une_dependance_inconnue_ne_passe_jamais_en_silence():
    for spec in cat.CATALOG:
        for dep in spec.depends_on:
            assert dep in cat.BY_KEY, f"{spec.key} dépend de {dep}, absent du registre"


def test_cles_uniques():
    keys = [s.key for s in cat.CATALOG]
    assert len(keys) == len(set(keys))


def test_cle_inconnue_est_bloquee_pas_autorisee_par_defaut():
    """Fail-closed (§3) : ce qu'on ne connaît pas ne se collecte pas."""
    assert cat.fetch_block_reason("serie_qui_nexiste_pas") is not None


# =============================================================================================
# Miroir du pipeline qui tourne
# =============================================================================================


def test_matrice_de_poids_du_quadrant_IDENTIQUE_au_moteur():
    """La matrice Bridgewater existe à deux endroits : la spec et le code d'agrégation. Si elles
    divergent, le terminal pondère autrement que ce que la spec dit — en silence."""
    from app.strategies.youssef import WEIGHTS
    assert cat.QUADRANT_WEIGHTS == WEIGHTS


def test_chaque_ligne_de_la_matrice_somme_a_1():
    for quadrant, row in cat.QUADRANT_WEIGHTS.items():
        assert round(sum(row.values()), 6) == 1.0, quadrant


def test_seules_D1_et_D5_sont_directionnelles():
    """« Additionner cinq scores D serait un contresens » : D2/D3 sont absorbés (poids 0),
    D4 est un multiplicateur, pas une direction."""
    assert cat.directional_dimensions() == ("D1", "D5")
    assert cat.DIMENSIONS["D2"].absorbed_by == "Arb1"
    assert cat.DIMENSIONS["D3"].absorbed_by == "Arb2"
    assert cat.DIMENSIONS["D2"].long_weight == 0.0
    assert cat.DIMENSIONS["D3"].long_weight == 0.0
    assert cat.DIMENSIONS["D4"].kind == "B"


def test_arbitrages_du_registre_ALIGNES_avec_ceux_que_le_moteur_emet():
    from app.strategies.youssef import compute_arbitrages, make_regime
    emitted = {a.arb_id: a for a in compute_arbitrages({}, make_regime("GREEN", 15.0, None))}
    assert set(emitted) == {s.arb_id for s in cat.ARBITRAGES}
    for spec in cat.ARBITRAGES:
        live = emitted[spec.arb_id]
        assert live.source_dim == spec.source_dim, spec.arb_id
        assert live.horizon == spec.horizon, spec.arb_id
        assert live.threshold == spec.threshold_label, spec.arb_id


def test_chaque_dimension_et_chaque_arbitrage_a_au_moins_une_ligne():
    by_dim = cat.by_dimension()
    for code in ("D1", "D2", "D3", "D4", "D5"):
        assert by_dim.get(code), code
    by_arb = cat.by_arbitrage()
    for spec in cat.ARBITRAGES:
        assert by_arb.get(spec.arb_id), spec.arb_id


def test_les_poids_internes_de_D1_somment_a_1():
    assert round(sum(cat.D1_WEIGHTS.values()), 6) == 1.0


# =============================================================================================
# Pièges de source — ceux qui cassent en silence
# =============================================================================================


def test_le_dataflow_ICP_est_MORT_aucun_identifiant_ne_doit_le_porter():
    """Discontinué le 04.02.2026, remplacé par HICP à structure de clé identique. Une clé ICP
    codée en dur renvoie une erreur — encore faut-il ne pas la réintroduire."""
    for spec in cat.CATALOG:
        if spec.identifier:
            assert not spec.identifier.startswith("ICP."), spec.key
    assert cat.BY_KEY["hicp_ez"].identifier.startswith("HICP.")


def test_le_code_de_zone_AMECO_est_une_constante_visible_pas_un_detail_noye():
    """« Le code zone AMECO suit les élargissements (EA20 → EA21) » : quand la zone euro
    s'agrandit, on doit savoir où changer un seul caractère."""
    assert cat.AMECO_ZONE == "EA20"
    assert cat.AMECO_ZONE in cat.BY_KEY["output_gap_ez"].identifier


def test_bundei_l_ecart_de_tenor_est_MESURE_pas_supposé():
    state = cat.bundei_roll_state(now=1785542400.0)          # 2026-08-01T00:00:00Z
    assert state["isin"] == "DE0001030575"
    assert 6.6 < state["residual_years"] < 6.8
    # La jambe US (T10YIE) reste à 10 ans constants : l'écart est déjà de plus de 3 ans.
    assert 3.2 < state["tenor_drift_years"] < 3.4
    assert state["status"] == "BASCULE_REQUISE"


def test_bundei_apres_echeance_la_serie_est_MORTE_pas_courte():
    state = cat.bundei_roll_state(now=2_100_000_000.0)       # bien après 04.2033
    assert state["status"] == "ECHU"
    assert state["residual_years"] <= 0


def test_bundei_horloge_douteuse_ne_produit_pas_un_faux_verdict():
    for bad in (float("nan"), float("inf"), None):
        assert cat.bundei_roll_state(now=bad)["status"] == "INCONNU"


def test_l_echeance_codee_en_dur_correspond_bien_a_la_date_annoncee():
    """La constante est un epoch (le module reste sans horloge ni `datetime`) — donc elle se
    vérifie ici, sinon personne ne la relit jamais."""
    from datetime import datetime, timezone
    assert (datetime.fromtimestamp(cat.BUNDEI["maturity_ts"], timezone.utc).strftime("%Y-%m")
            == "2033-04")


# =============================================================================================
# Incohérences déclarées — signalées, pas patchées en douce
# =============================================================================================


def test_les_incoherences_connues_sont_DECLAREES_et_ouvertes():
    """Le protocole des artefacts est explicite : « à trancher, pas des bugs à patcher en
    douce ». Le registre les porte, avec les deux valeurs en présence."""
    topics = {c["topic"] for c in cat.KNOWN_CONFLICTS}
    assert {"d4_red_coeff", "d4_ttl_vs_nfci", "k_etape1_vs_seuils_etape3"} <= topics
    red = next(c for c in cat.KNOWN_CONFLICTS if c["topic"] == "d4_red_coeff")
    assert "0.4" in str(red["values"]) and "0.0" in str(red["values"])
    assert red["status"] == "OUVERT"


def test_l_age_du_CACHE_et_l_age_d_OBSERVATION_sont_deux_axes_distincts():
    """Incohérence (2), tranchée. Le TTL de 4 h de D4 gouverne l'âge de NOTRE COPIE — cet axe-là
    est satisfiable par toutes les composantes. L'âge de la PUBLICATION suit la fréquence de la
    série : un NFCI hebdomadaire est légitimement vieux d'une semaine.

    Constat qui va plus loin que la spec : VIXCLS et BAMLH0A0HYM2 sont des séries de CLÔTURE
    quotidienne — un seuil de 4 h sur l'âge d'OBSERVATION les tuerait aussi, pas seulement le
    NFCI. C'est ce qui condamne la lecture littérale, pas le seul cas hebdomadaire."""
    ttl = cat.DIMENSIONS["D4"].ttl_s
    assert cat.cache_max_age_s("vixcls") == pytest.approx(ttl)
    assert cat.cache_max_age_s("nfci") == pytest.approx(ttl)
    assert cat.observation_max_age_s("nfci") > cat.observation_max_age_s("vixcls")
    assert cat.observation_max_age_s("vixcls") > ttl


def test_une_cle_inconnue_est_PERIMEE_d_office_sur_les_deux_axes():
    assert cat.cache_max_age_s("inconnue") == 0.0
    assert cat.observation_max_age_s("inconnue") == 0.0


def test_une_serie_trimestrielle_ne_se_z_score_pas_sur_252_jours():
    """« Le z-score sur 252 jours n'a pas de sens sur une série trimestrielle : il faut définir
    la fenêtre en OBSERVATIONS. »"""
    assert cat.zscore_window("vixcls") == 252
    assert 0 < cat.zscore_window("nfa") < 252


# =============================================================================================
# Pureté
# =============================================================================================


def test_module_PURE_aucune_lecture_d_horloge():
    import inspect
    src = inspect.getsource(cat)
    for banned in ("time.time", "datetime", "perf_counter", "monotonic"):
        assert banned not in src, banned
