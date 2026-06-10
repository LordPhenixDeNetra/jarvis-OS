# BACKLOG — Refonte architecturale jarvis-OS

Réceptacle des problèmes hors-périmètre identifiés pendant la refonte (CDC `CDC_refonte_architecture.md` §0 règle 1 et règle 5). On note, on ne corrige PAS dans la phase courante.

Format d'entrée : `- [PHASE X] <description> — <fichier/zone> — <pourquoi pas maintenant>`.

## Phase A

_(en cours)_

## Phase B

_(à venir)_

## Phase C

_(à venir)_

## Phase D

_(à venir)_

## Phase E

_(à venir)_

## Phase F

- **GATE B9 (install à froid) BLOQUANT pour le merge final** — décalé de fin de B sur décision Barth, doit passer sur la lane CI complète avant le merge `refonte/architecture-couches` → `main`. Libellé verrouillé dans [gates_B8_B9.md](gates_B8_B9.md) : install Ubuntu propre + deps lourdes réelles + boot effectif via smoke_runtime --fake-llm.

## Post-refonte (hors §9 « Hors périmètre »)

- Retrait des shims racine `main.py` / `voice_agent.py` — conservés une version pour les appelants externes (CDC §9).
- Réécriture front (ES modules `capabilities.js` / `macropad_2k.js`) — CDC ultérieur.
- mypy strict généralisé sur 46k lignes — chantier séparé, seul kernel + conformité Protocols couverts par F.1.3bis.
- Git LFS / réécriture historique pour gros binaires.
