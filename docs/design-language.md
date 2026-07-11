# Langage visuel — cholismo terminal

> Sortie de la **Loop 6** (`CLAUDE.md §13`, skill `/design`) : « inspiré des terminaux
> financiers pour leurs **principes** — jamais copié ». On emprunte l'IDÉE, jamais
> l'EXPRESSION protégée. Chaque élément visible ci-dessous est original et justifié.

---

## 1. Principes extraits (l'IDÉE, pas les pixels)

De la lignée des terminaux financiers professionnels, on retient des **principes de
métier**, pas une apparence :

| Principe emprunté | Pourquoi il sert Cholismo | Traduction cholismo |
|---|---|---|
| **Densité tabulaire** | 6 blocs de schéma lisibles d'un coup d'œil | grille 5 zones, panneaux compacts `border + header mnémonique` |
| **Clavier-first** | décision rapide, mains sur le clavier | `A/B/C/D` focus, `1-9` espaces, barre de commande `/`, `V` vue |
| **Latence basse** | le hot path décisionnel est < ~200 ms (§7) | SSE segmenté rapide/lent, rendu partiel, feedback < 100 ms |
| **Monospace pour les chiffres** | alignement, lecture de colonnes de nombres | `JetBrains Mono` sur toutes les valeurs numériques |
| **Couleur sémantique** | l'état se lit à la couleur | VERT/JAUNE/ROUGE **doublés** forme + icône + position (§3) |
| **Panneaux composables** | réarranger sans casser la donnée | espaces de travail = pure projection d'affichage, 1 panneau = 1 champ |

Ces principes sont **non protégeables** : ce sont des idées d'ergonomie, pas une charte.

---

## 2. Identité propre (l'EXPRESSION, 100 % cholismo)

### 2.1 Design tokens (`frontend/tailwind.config.ts`)
Palette **choisie pour Cholismo**, pas reprise d'un produit identifiable :

- **Fond** — noir profond `#06080b` → `#0e141c` (dark-mode dense). *Choix de contraste
  pour la lecture prolongée, pas une charte signature.*
- **Sony (S1)** — ROUGE framboise `#f43f5e` · **Youssef (S2)** — JAUNE citron `#facc15`
  (arbitrage opérateur, D-024) : deux couleurs d'opérateur **assignées par le domaine**
  (§3), pas décoratives. Teintes volontairement **distinctes des statuts de risque**
  (framboise ≠ rouge saumon `#f87171` ; citron ≠ ambre `#fbbf24` ≠ or Router) et
  **jamais seules** : chaque bloc porte un badge texte `S1 · SONY` / `S2 · YOUSSEF` /
  `ROUTER` / `SYSTÈME` (mixte : `S1 + S2`) + un liseré gauche.
- **Router** — OR `#f0b429` en **bordure/trait uniquement, jamais remplissage** : évite
  la collision avec le JAUNE (amber) du risque — décision d'accessibilité maison.
- **Risque** — VERT `#34d399` / JAUNE `#fbbf24` / ROUGE `#f87171`, **toujours** doublés
  d'une forme (`● / ▲ / ⬢`) + icône + libellé (daltonisme rouge/vert ~8 % des hommes).
- **Fraîcheur** — `stale` grisé, `absent` = « PAS DE DONNÉES » (fail-closed, §3).

### 2.2 Nomenclature de commandes maison
Barre de commande cholismo : `/` ouvre la ligne, on tape un **mnémonique maison**
(`RECAP`, `MODELIVE`, `PARAMS`, `MICRO`, `MACRO`, `DISCIPLINE`, `B4`, `C4`…), `Entrée`
exécute. Les mnémoniques sont dérivés des **blocs du schéma** et des **vues**, pas d'un
dictionnaire propriétaire.

### 2.3 Vocabulaire
Termes du **domaine trading** (GO/NO-GO, Phase 0, self-check C5, streak, calibration,
sizing, réconciliation) — ce sont des concepts métier, pas une marque.

---

## 3. Checklist anti-copie (revue à chaque évolution UI)

- [x] **Aucune charte de couleurs signature** reprise — la palette est choisie pour le
  contraste et le mapping opérateur, documentée ci-dessus.
- [x] **Aucun code de commande propriétaire.** ⚠️ Le mnémonique d'exécution **`<GO>` de
  Bloomberg a été retiré** de la barre de commande (remplacé par un libellé cholismo
  natif). Le **GO / NO-GO métier** (verdict Phase 0) reste : c'est un terme du domaine,
  pas une marque.
- [x] **Aucun layout / logo / nom** identifiable à un terminal existant — grille 5 zones
  et espaces nommés sont propres à Cholismo.
- [x] **Mentions de terminaux dans le produit** : aucune. Nommer Bloomberg / Eikon /
  FactSet / ICE / Aladdin / Murex-Calypso reste cantonné à la **doc interne** comme
  source d'inspiration justifiée (`DECISIONS.md §D-000`), jamais rendu à l'écran ni dans
  les commentaires de style.

**Règle du doute** : au moindre doute sur un emprunt, on s'éloigne et on trace la décision
dans `DECISIONS.md`.

---

## 4. Emprunts justifiés (traçabilité)

| Emprunt | Source d'inspiration | Justification |
|---|---|---|
| Densité + monospace | terminaux pro en général | lisibilité de colonnes de nombres, principe non protégeable |
| Clavier-first + ligne de commande | lignée des terminaux financiers | vitesse de décision ; **mnémoniques et libellés 100 % maison** |
| Sparklines inline | dataviz financière courante | forme d'onde minimale, implémentation SVG maison, zéro dépendance |
| Couleur sémantique + forme | standards d'accessibilité | doublage couleur/forme/icône = exigence, pas emprunt esthétique |

---

## 5. Ce qui reste interdit

- Reproduire un **écran signature** reconnaissable d'un produit existant.
- Afficher un **code de commande propriétaire** (`<GO>` et assimilés).
- Utiliser un **nom / logo / charte** d'un terminal commercial dans le produit livré.
- Laisser la **couleur seule** porter une information de risque.

> Toute nouvelle vue passe par `/design` avant implémentation, et met à jour ce fichier.
