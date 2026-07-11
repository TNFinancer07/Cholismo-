# Skills cholismo — installation (format recommandé)

Ces skills branchent tes loops (`CLAUDE.md` / `RUNTIME_LOOPS.md`) sur des raccourcis `/`.
Format skills = même invocation `/nom` que les slash commands, **plus** l'invocation autonome par Claude quand la description matche le contexte.

## Installer

Copie le dossier `.claude/skills/` à la **racine de ton dépôt** cholismo :

```
ton-repo/
├── .claude/
│   └── skills/
│       ├── stack/SKILL.md
│       ├── feature/SKILL.md
│       ├── bugfix/SKILL.md
│       ├── refactor/SKILL.md
│       ├── devil/SKILL.md
│       ├── polish/SKILL.md
│       ├── design/SKILL.md
│       ├── loop-check/SKILL.md
│       ├── done/SKILL.md
│       └── commit/SKILL.md
├── CLAUDE.md
└── RUNTIME_LOOPS.md
```

Le **nom du dossier** = le nom de la commande. `feature/SKILL.md` → `/feature`.
L'édition d'un skill est prise en compte dans la session en cours ; sinon tape `/` pour rafraîchir la liste.

- **Projet** (`.claude/skills/`) : partagé via git avec ton dépôt.
- **Perso** (`~/.claude/skills/`) : dispo dans tous tes projets, privé à ta machine.

## Les skills

| Commande | Rôle | Loop |
|---|---|---|
| `/stack` | Choisir et verrouiller le stack | Loop 0 |
| `/feature <desc>` | Développer une feature proprement | Loop 1 |
| `/bugfix <bug>` | Corriger un bug (repro → cause racine) | Loop 2 |
| `/refactor <cible>` | Refactor sûr, comportement inchangé | Loop 3 |
| `/devil [cible]` | Revue critique avant commit | Loop 4 |
| `/polish <feature>` | Soigner l'ergonomie | Loop 5 |
| `/design <zone>` | Langage visuel, inspiré jamais copié | Loop 6 |
| `/loop-check <fichier>` | Auditer une boucle runtime | RUNTIME_LOOPS |
| `/done` | Vérifier la Definition of Done | — |
| `/commit [msg]` | Commit atomique et propre | — |

## Différences avec le format `.claude/commands/`

- Un skill est un **dossier** `<nom>/SKILL.md` (il peut embarquer des fichiers annexes), pas un simple `.md`.
- Frontmatter : `name` (obligatoire, = nom du dossier) et `description` (indique **quoi** + **quand** l'utiliser → sert à l'invocation autonome). `argument-hint` et `allowed-tools` restent supportés.
- Même invocation `/nom`. Si un skill et une commande portent le même nom, **le skill l'emporte**.
- Noms réservés évités : `code-review` et `verify` sont des skills fournis par Claude Code.

## Exemples

```
/design vue watchlist temps réel
/feature ajouter l'autocomplétion des commandes
/bugfix crash quand on tape Ctrl-C pendant un fetch de marché
/loop-check src/render_loop
/devil
/commit ajoute l'autocomplétion des commandes
```

## Note « inspiré, jamais copié »

`/design` (Loop 6) encadre l'inspiration des terminaux financiers (Bloomberg, Eikon, TradingView, FactSet…) : on emprunte les **principes** (densité, clavier-first, couleur sémantique), jamais l'**expression** protégée (layout signature, charte de couleurs, codes de commandes propriétaires, marque). Chaque choix visible de cholismo doit être original et documenté dans `docs/design-language.md`.
