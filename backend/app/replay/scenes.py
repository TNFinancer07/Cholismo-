"""Scènes de microstructure SCRIPTÉES — de quoi exercer B1/B3/B4 (D-061).

Le générateur produisait des prints indépendants : un tape statistiquement plausible mais sans
aucun des phénomènes que le Niveau 2 mesure. Conséquence, jamais dite jusqu'ici : **B1, B3 et B4
n'étaient exercés que sur des scènes construites à la main dans leurs propres tests.** Rejouer
mille ticks de bruit ne les faisait pas réagir — donc ne prouvait rien, ni dans un sens ni dans
l'autre.

Chaque scène ci-dessous fabrique un phénomène RECONNAISSABLE et rend sa **vérité terrain** : où
elle commence, où elle finit, dans quel sens, et ce qu'on attend de la porte concernée.

**Ce que ça prouve, et ce que ça ne prouve pas.** Une scène scriptée peut INFIRMER : si un mur
qu'on a explicitement fait recharger ne produit aucun B1, quelque chose est cassé. Elle ne peut
pas VALIDER : elle dit que le calculateur réagit à ce qu'on a écrit, pas qu'il mesure le marché.
Seul un vrai tape le dira. C'est un substitut en attendant, pas un remplaçant.

Les attentes sont **qualitatives** (signe, ordre de grandeur, sens) et jamais des valeurs
exactes : réencoder le résultat du calculateur dans le générateur ferait un test qui se vérifie
lui-même.

Le module est **PUR** : aucune horloge lue, aucun fichier écrit. Les horodatages sont ceux qu'on
lui passe, et la même graine rend les mêmes lignes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

Row = dict[str, str]


@dataclass
class Scene:
    """Un phénomène scripté, avec ce qu'on attend de lui.

    `debut_ts` sert aussi de **marqueur de sweep** pour la scène `sweep` : B4 mesure de part et
    d'autre d'un instant, et cet instant doit venir de la vérité terrain, pas d'une détection
    qu'on chercherait justement à éprouver.
    """
    nom: str
    porte: str                              # B1 · B2 · B3 · B4
    debut_idx: int = 0                      # index de ligne dans le FICHIER (informatif)
    fin_idx: int = 0
    debut_ts: float = 0.0                   # la vérité qui SURVIT au filtrage des lignes
    fin_ts: float = 0.0
    direction: Optional[str] = None         # ASK_SWEEP · BID_SWEEP
    wall_price: Optional[float] = None
    wall_side: Optional[str] = None
    attendu: str = ""                       # qualitatif, jamais une valeur exacte
    lignes: list[Row] = field(default_factory=list)

    def as_truth(self) -> dict[str, Any]:
        """Vérité terrain sérialisable — ce qui part dans le fichier `.truth.json`.

        Les `*_idx` sont INFORMATIFS : le moteur de replay écarte les lignes illisibles, donc un
        index de fichier ne désigne pas le même tick qu'un index de tape. Ce sont les
        HORODATAGES qui font foi, eux survivent au filtrage.
        """
        return {"nom": self.nom, "porte": self.porte, "debut_idx": self.debut_idx,
                "fin_idx": self.fin_idx, "debut_ts": round(self.debut_ts, 3),
                "fin_ts": round(self.fin_ts, 3), "direction": self.direction,
                "wall_price": self.wall_price, "wall_side": self.wall_side,
                "attendu": self.attendu}


def _row(ts: float, prix: float, taille: int, side: str,
         bid: Optional[float], ask: Optional[float]) -> Row:
    return {"timestamp": f"{ts:.3f}", "price": f"{prix:.2f}", "volume": str(taille),
            "side": side, "bid_vol": "" if bid is None else f"{bid:.1f}",
            "ask_vol": "" if ask is None else f"{ask:.1f}"}


def _borner(scene: Scene) -> Scene:
    """Renseigne `debut_ts`/`fin_ts` depuis les lignes réellement écrites. Les recopier à la main
    dans chaque constructeur finirait par mentir le jour où une scène gagne une ligne."""
    if not scene.lignes:
        # Une scène vide bornée à 0.0 placerait la vérité terrain en 1970 : le générateur y
        # recollerait le bruit et tout le tape remonterait le temps. Mieux vaut casser ici.
        raise ValueError(f"scène « {scene.nom} » sans aucune ligne — rien à borner")
    scene.debut_ts = float(scene.lignes[0]["timestamp"])
    scene.fin_ts = float(scene.lignes[-1]["timestamp"])
    return scene


def sweep(ts: float, prix: float, tick: float, rng: random.Random,
          direction: str = "ASK_SWEEP") -> Scene:
    """Rafale directionnelle qui TRAVERSE plusieurs niveaux en quelques centaines de ms.

    `ASK_SWEEP` = agression ACHETEUSE qui balaie l'ask, donc le prix monte. La profondeur du
    côté attaqué s'épuise à mesure — c'est ce qui distingue un sweep d'une simple série d'achats.
    """
    monte = direction == "ASK_SWEEP"
    side = "BUY" if monte else "SELL"
    lignes: list[Row] = []
    t, p = ts, prix
    ask, bid = 300.0, 300.0
    for _niveau in range(6):
        for _ in range(rng.randint(3, 5)):
            t += rng.uniform(0.008, 0.030)          # rafale : quelques ms entre prints
            taille = rng.randint(15, 60)
            # Le côté ATTAQUÉ se vide ; l'autre reste garni.
            if monte:
                ask = max(5.0, ask - taille * 1.4)
            else:
                bid = max(5.0, bid - taille * 1.4)
            lignes.append(_row(t, p, taille, side, bid, ask))
        p = round(p + (tick if monte else -tick), 4)
        ask, bid = (280.0, 300.0) if monte else (300.0, 280.0)
    return _borner(Scene(
        nom="sweep", porte="B4", direction=direction, lignes=lignes,
        attendu="débit d'agression APRÈS > débit AVANT (B4 > 1) et B2 très déséquilibré "
                f"du côté {'acheteur' if monte else 'vendeur'}"))


def _mur(nom: str, profondeurs: list[float], attendu: str, ts: float, prix: float,
         rng: random.Random, cote: str = "BID") -> Scene:
    """Un mur attaqué, dont la profondeur suit la trajectoire donnée.

    C'est exactement ce que B1 mesure : `consommé` = taille initiale − minimum observé,
    `rechargé` = taille finale − minimum, ratio = rechargé / consommé.
    """
    lignes: list[Row] = []
    t = ts
    attaque = "SELL" if cote == "BID" else "BUY"        # on attaque le mur, on ne le pose pas
    for taille_mur in profondeurs:
        for _ in range(rng.randint(1, 3)):
            t += rng.uniform(0.04, 0.12)
            bid = taille_mur if cote == "BID" else 250.0
            ask = 250.0 if cote == "BID" else taille_mur
            lignes.append(_row(t, prix, rng.randint(3, 18), attaque, bid, ask))
    return _borner(Scene(nom=nom, porte="B1", wall_price=prix, wall_side=cote,
                         lignes=lignes, attendu=attendu))


def wall_refill(ts: float, prix: float, tick: float, rng: random.Random) -> Scene:
    """Un mur se fait manger puis **se recharge** au même niveau : une défense qui tient."""
    return _mur("wall_refill", [400.0, 300.0, 180.0, 60.0, 40.0, 120.0, 260.0, 380.0],
                "mur creusé de 400 à 40 puis RECHARGÉ à 380 → B1 proche de 1 "
                "(rechargé/consommé ≈ 340/360)", ts, prix, rng)


def wall_fail(ts: float, prix: float, tick: float, rng: random.Random) -> Scene:
    """Le même mur, mangé puis **jamais reconstitué** : la défense lâche.

    Cette scène existe pour une raison précise, trouvée en éprouvant les tests : sur un mur qui
    se recharge presque intégralement, `rechargé/consommé` et son INVERSE valent tous deux ≈ 1.
    Une inversion de la formule passait donc inaperçue. Un rechargement PARTIEL casse la symétrie
    et rend le sens du rapport observable.
    """
    return _mur("wall_fail", [400.0, 300.0, 180.0, 60.0, 40.0, 70.0, 100.0, 120.0],
                "mur creusé de 400 à 40 et rechargé à 120 SEULEMENT → B1 nettement < 1 "
                "(rechargé/consommé ≈ 80/360) — la défense lâche", ts, prix, rng)


def absorption(ts: float, prix: float, tick: float, rng: random.Random) -> Scene:
    """Gros volume au MÊME prix, sans que le prix bouge : le mur encaisse.

    Le contraste avec `sweep` est le point : même agressivité, mais **aucun niveau traversé**. Un
    calculateur qui rendrait la même chose sur les deux ne mesurerait pas la microstructure.
    Le mur est entamé puis tenu — sans déplétion du tout, B1 n'aurait rien à mesurer et le dirait
    (« défense non éprouvée »), ce qui est correct mais ne prouve pas grand-chose.
    """
    lignes: list[Row] = []
    t = ts
    profondeurs = [380.0, 340.0, 300.0, 290.0, 330.0, 370.0]
    for taille_mur in profondeurs:
        for _ in range(rng.randint(2, 4)):
            t += rng.uniform(0.02, 0.06)
            # Le mur reste GARNI malgré l'agression : c'est ça, l'absorption.
            lignes.append(_row(t, prix, rng.randint(25, 70), "SELL", taille_mur, 240.0))
    return _borner(Scene(
        nom="absorption", porte="B1", wall_price=prix, wall_side="BID", lignes=lignes,
        attendu="volume élevé, prix IMMOBILE, mur qui tient → B1 mesurable et élevé, B2 nettement "
                "vendeur, et B3 refusé faute d'extrême (prix plat)"))


def accumulation(ts: float, prix: float, tick: float, rng: random.Random) -> Scene:
    """Beaucoup de PETITES ventes contre quelques GROS achats, au même prix.

    Signature d'une accumulation : le nombre de prints dit « vendeur », le volume dit
    « acheteur ». C'est précisément ce que la pondération de B2 existe pour trancher — « un print
    de 100 lots ne pèse pas comme un de 1 lot ». Sans une scène où les deux lectures divergent,
    un B2 compté par PRINTS passe tous les tests : défaut trouvé en mutant le calculateur.
    """
    lignes: list[Row] = []
    t = ts
    for i in range(30):
        t += rng.uniform(0.02, 0.08)
        lignes.append(_row(t, prix, rng.randint(1, 3), "SELL", 300.0, 300.0))
        if i % 6 == 5:                                   # un gros acheteur encaisse le lot
            t += rng.uniform(0.01, 0.03)
            lignes.append(_row(t, prix, rng.randint(150, 250), "BUY", 300.0, 300.0))
    return _borner(Scene(
        nom="accumulation", porte="B2", wall_price=prix, lignes=lignes,
        attendu="prints majoritairement VENDEURS mais volume majoritairement ACHETEUR → "
                "B2 > 0,8 si (et seulement si) la pondération se fait au volume"))


def rejection(ts: float, prix: float, tick: float, rng: random.Random,
              bas: bool = True) -> Scene:
    """Le prix va chercher un extrême puis se fait REJETER.

    B3 mesure le delta net des prints POSTÉRIEURS à l'extrême : positif = le bas a été rejeté
    (l'acheteur a repris la main). La scène écrit donc une descente vendeuse, un point bas, puis
    une reprise acheteuse franche.
    """
    lignes: list[Row] = []
    t, p = ts, prix
    for _ in range(6):                                   # descente : les vendeurs poussent
        t += rng.uniform(0.03, 0.09)
        p = round(p - tick if bas else p + tick, 4)
        lignes.append(_row(t, p, rng.randint(5, 20), "SELL" if bas else "BUY", 200.0, 200.0))
    extreme = p
    for _ in range(12):                                  # rejet : l'autre camp reprend la main
        t += rng.uniform(0.03, 0.09)
        pas = tick * rng.choice((0, 1, 1))
        p = round(p + pas if bas else p - pas, 4)
        lignes.append(_row(t, p, rng.randint(15, 45), "BUY" if bas else "SELL", 260.0, 180.0))
    return _borner(Scene(
        nom="rejection", porte="B3", lignes=lignes, wall_price=extreme,
        attendu=("extrême BAS rejeté, delta net acheteur après l'extrême → B3 > 0"
                 if bas else "extrême HAUT rejeté → B3 < 0")))


def double_bottom(ts: float, prix: float, tick: float, rng: random.Random) -> Scene:
    """Le prix touche un creux, rebondit, **y revient**, puis part pour de bon.

    Scène écrite pour un point précis que le calculateur traite explicitement : l'extrême retenu
    doit être la DERNIÈRE touche, pas la première. Partir de la première ferait compter la vente
    du second creux comme du rejet acheteur — le nombre resterait crédible, il désignerait juste
    l'inverse de ce qui s'est passé. Le chemin de prix est ÉCRIT, pas tiré au sort : c'est la
    répétition exacte du creux qui fait toute la scène.
    """
    lignes: list[Row] = []
    t = ts
    bas = round(prix - 5 * tick, 4)

    def pousser(cible: float, n: int, side: str, taille: tuple[int, int]) -> None:
        nonlocal t
        for _ in range(n):
            t += rng.uniform(0.03, 0.08)
            lignes.append(_row(t, cible, rng.randint(*taille), side, 200.0, 200.0))

    for k in range(4, 0, -1):                       # descente vendeuse jusqu'au creux
        pousser(round(prix - k * tick, 4), 1, "SELL", (10, 25))
    pousser(bas, 2, "SELL", (10, 25))               # PREMIÈRE touche du creux
    for k in (3, 2):                                # rebond timide
        pousser(round(prix - k * tick, 4), 2, "BUY", (8, 14))
    for k in (3, 4):                                # on y retourne, et lourdement
        pousser(round(prix - k * tick, 4), 3, "SELL", (50, 70))
    pousser(bas, 2, "SELL", (50, 70))               # SECONDE touche — le vrai départ du rejet
    for k in (4, 3, 2, 1, 0, -1, -2):               # rejet franc, pour de bon
        pousser(round(prix - k * tick, 4), 2, "BUY", (28, 42))
    return _borner(Scene(
        nom="double_bottom", porte="B3", lignes=lignes, wall_price=bas,
        attendu="creux TOUCHÉ DEUX FOIS puis rejeté → B3 nettement positif si le delta part de "
                "la dernière touche ; proche de zéro s'il part de la première"))


# Constructeurs à signature UNIFORME `(ts, prix, tick, rng) -> Scene` : le générateur les enchaîne
# sans savoir ce que chacun fabrique.
SCENES: dict[str, Callable[[float, float, float, random.Random], Scene]] = {
    "sweep": sweep,
    "wall_refill": wall_refill,
    "wall_fail": wall_fail,
    "absorption": absorption,
    "accumulation": accumulation,
    "rejection": rejection,
    "double_bottom": double_bottom,
}
SCENES_DISPONIBLES = tuple(SCENES)

# Ordre par défaut : chaque phénomène une fois, les quatre portes couvertes. Trois scènes ne sont
# là que pour rendre une erreur OBSERVABLE, et n'existeraient pas sans la passe de mutation :
# `wall_fail` (sens du rapport B1), `accumulation` (B2 pondéré au volume et non au nombre de
# prints), `absorption` (traverser ≠ encaisser, face à `sweep`), `double_bottom` (le rejet part
# de la DERNIÈRE touche de l'extrême).
SEQUENCE_DEFAUT = ("sweep", "wall_refill", "wall_fail", "absorption", "accumulation",
                   "rejection", "double_bottom")
