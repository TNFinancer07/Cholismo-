# P4 — checklist de vérification navigateur

> Clôture de la phase P4 (D-088 → D-090). Ce document existe parce que **rien de ce qui suit
> n'a été exécuté dans un navigateur**. `node --check` valide la *syntaxe* des deux fichiers, pas
> leur comportement.
>
> **Correction (D-092)** : ce paragraphe affirmait que `vitest` et `tsc` étaient absents de
> l'environnement. C'était faux — `frontend/src/` a 125 tests et un typecheck `strict` verts,
> tous deux en CI depuis D-092. Mais ils ne changent rien ici : vérifié, **la maquette v17 n'est
> couverte ni par `tsc` ni par aucun test** (elle est hors de `include: ["src"]`). Le navigateur
> reste le seul juge de ce qui suit.
>
> Les vérifications sont ordonnées par **risque décroissant** : celles du haut sont celles où je
> me suis déjà trompé aujourd'hui.

## Lancer

```bash
# 1. backend (le worker options est optionnel — sans lui, options.sync passera STALLED, et c'est
#    le comportement attendu, pas une panne à corriger)
cd backend && .venv/bin/uvicorn app.main:app --port 8000

# 2. frontend — Vite sert `public/` à la racine
cd frontend && npm run dev        # puis http://localhost:5173/v17/
```

**Si rien n'arrive et que la console montre des erreurs CORS** : le backend autorise `*`, mais en
cas de blocage, ouvrir la console et poser `window.CHOLISMO_API = '/api'` **avant** le chargement
de `live.js`, ou passer par le proxy Vite déjà configuré (`/api` → `localhost:8000`).

---

## 1. L'ancrage du bandeau — le point le plus fragile

`live.js` insère `#cho-live` **après** `header.topbar`. Ce sélecteur est déduit de la lecture du
HTML, pas observé.

- ✅ **Attendu** : un bandeau monospace sous l'en-tête, portant `contexte …`, `O5 …`, puis cinq
  badges `core.tick`, `options.sync`, `o5.kurtosis`, `gates.eval`, `ui.broadcast`.
- ❌ **Si absent** : `document.querySelector('header.topbar')` rend `null` → `ensureStrip()`
  abandonne et **tout le rendu s'arrête** (le `return` est en tête de `render()`). Chercher le
  vrai conteneur d'en-tête et corriger le sélecteur — c'est un changement d'une ligne.

## 2. La maquette n'est pas abîmée

C'est la régression que D-090 a corrigée, et celle qu'il faut confirmer.

- ✅ Les jauges **B1–B4** (`#w1`–`#w4`, sparklines `#s1`–`#s3`, barre `#g4`) gardent leur
  comportement d'origine — B4 continue d'animer sa jauge.
- ✅ L'onglet **6 · Backtest & Monte-Carlo** s'ouvre intact (rejeu, Monte-Carlo, grille 4×4).
- ✅ Le journal `#jTable` de la maquette garde son contenu ; le blotter live apparaît **sous**
  lui, dans une table `#cho-blotter` distincte.
- ❌ Si l'un des trois casse, c'est qu'un sélecteur `#cho-*` collisionne encore avec la maquette.

## 3. « Aucune valeur inventée » tenu jusqu'à l'écran

- ✅ **Backend arrêté** → prix, contexte, O5 affichent `—`. Jamais un zéro, jamais une dernière
  valeur figée.
- ✅ **Carnet non publié** → le DOM montre `—` **et aucune barre de volume** (pas de barre à
  largeur nulle, qui suggérerait une mesure).
- ✅ **Sans print neuf** → le tape **reste immobile**. Un tape qui défile sur un flux mort a l'air
  vivant : c'est le pire affichage possible.
- ✅ **Worker options arrêté** → `options.sync` passe `STALLED` après ~90 s, le contexte passe
  `STALE`, et les niveaux (γ0, murs) cessent d'être affichés.

## 4. La cadence

- ✅ Le bandeau se rafraîchit à ~250 ms, pas à chaque message SSE (dirty flag).
- ❌ Si l'écran scintille ou si le CPU monte, le *dirty flag* ne joue pas son rôle.

## 5. Les états de santé

- ✅ `core.tick` s'affiche **`NOT_IMPLEMENTED` en rouge**, pas en vert. C'est délibéré (D-073) :
  une capacité annoncée et absente n'est pas un état neutre.
- ✅ Couper le backend → les badges cessent d'être mis à jour ; la reconnexion SSE se fait toute
  seule après ~2 s.

---

## Ce qui est prouvé, et ce qui ne l'est pas

| | État |
|---|---|
| Backend (1747 tests, ruff + mypy clean) | **prouvé**, et rejoué en CI |
| Endpoints `/setups`, `/setups/calibration`, `/loops/health` | **prouvés**, testés + appelés en réel |
| Canal SSE `options` (contexte, O5, santé, gates) | **prouvé** en réel (curl) |
| `frontend/src/` — 125 tests + `tsc --noEmit` strict (81 fichiers) | **prouvé**, et rejoué en CI |
| `live.js` + maquette v17 | **syntaxe seule** — comportement non vérifié, non couvert par la CI |

## Ce qui reste ouvert après P4

- **Aucun setup ne s'arme encore en rejeu.** La cause est le générateur synthétique (barres
  dégénérées, 25 min pour un ATR lent qui en exige 50), pas la chaîne — voir D-087. Seule une
  séance MBO réelle fermera ce point.
- **La magnitude du biais de touché reste non chiffrée** depuis D-078. Le harnais est prêt ; il
  lui manque la donnée.
- **La heatmap** de la maquette conserve son profil pseudo-aléatoire déterministe (`Math.sin`,
  pas `Math.random`) : le backend publie `liquidity_heatmap` en DELTA (colonne courante), et
  l'adapter demande un travail de colonne à colonne qui n'est pas dans cette tranche.
