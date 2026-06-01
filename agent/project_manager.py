"""ProjectManager — analyse une mission et la décompose en étapes exécutables."""

from __future__ import annotations

import json
import re

from loguru import logger

from agent.project_store import ProjectStore
from agent.schemas import Project, Step, StepStatus

_PLANNING_SYSTEM = """\
Tu es un chef de projet expert. Analyse la demande utilisateur et décompose-la en étapes
précises et exécutables par un agent autonome travaillant dans un workspace isolé.

Règles générales :
- Chaque étape est atomique (une seule action claire)
- Marque requires_approval=true pour : push git, envoi email/message, appel API avec side effects,
  suppression de fichiers, déploiement en production
- Maximum 12 étapes (RAPPORT.md inclus)
- Sois réaliste sur ce qui est faisable dans un répertoire isolé

Règles qualité obligatoires :
- Insère une étape de vérification/test toutes les 3-4 étapes de production (exécuter le code,
  vérifier les liens HTML, tester une fonctionnalité clé)
- Ajoute une étape de test final avant la livraison

Types de projet :
- "website"       : site HTML/CSS/JS, landing page, portfolio
- "python_script" : script Python, automatisation, traitement de données
- "content"       : document, rapport, contenu textuel
- "fusion_360"    : modélisation 3D dans Autodesk Fusion 360
- "generic"       : tout autre type

Règles spéciales pour fusion_360 :
- Détecte fusion_360 si la demande mentionne Fusion 360, CAO, modélisation 3D,
  impression 3D, STL, coque, boîtier, pièce 3D, etc.
- Chaque étape doit décrire EXACTEMENT l'opération Fusion 360 à faire avec l'outil fusion_360.
- NE PAS utiliser execute_cli ou write_file pour des tâches Fusion 360.
- L'agent dispose de l'outil fusion_360(action="execute_script", script="...")
  pour exécuter des scripts Python Fusion API.
- Les scripts Fusion utilisent adsk.core, adsk.fusion, et les CENTIMÈTRES (10mm → createByReal(1)).
- Chaque étape = une opération (sketch, extrusion, fillet, shell, export STL, etc.)
- Toujours prendre un screenshot après les opérations importantes.
- requires_network=false (Fusion est local)
- Exemple d'étape Fusion : "Créer le sketch de base 14.3x7.1 cm sur le plan XY,
  puis l'extruder de 1.5 cm vers le haut avec l'outil fusion_360."

Réseau :
- requires_network=true si le projet nécessite internet (npm install, pip install, API externe,
  téléchargement de ressources)
- requires_network=false pour tout ce qui est faisable offline (dont Fusion 360)

Réponds UNIQUEMENT avec du JSON valide (sans markdown, sans commentaires) :
{
  "title": "Titre court du projet (< 40 chars)",
  "project_type": "website|python_script|content|fusion_360|generic",
  "requires_network": false,
  "steps": [
    {
      "id": "step_001",
      "title": "Titre de l'étape (< 50 chars)",
      "description": "Description précise de ce que l'agent doit faire (1-3 phrases)",
      "requires_approval": false
    }
  ]
}
"""


class ProjectManager:
    def __init__(self) -> None:
        self._store = ProjectStore()

    async def create_project(self, mission: str, timeout_minutes: int = 30) -> Project:
        from config.settings import settings
        from llm.api import AnthropicProvider

        llm = AnthropicProvider(max_tokens=2048, model=settings.voice_anthropic_model)

        logger.info("ProjectManager planning", mission=mission[:80])

        raw = await llm.complete(
            messages=[{"role": "user", "content": f"Mission : {mission}"}],
            system=_PLANNING_SYSTEM,
            stream=False,
        )
        assert isinstance(raw, str)

        plan = self._parse_plan(raw)
        plan = self._add_quality_steps(plan)
        project = self._store.create_project(
            mission=mission,
            title=plan["title"],
            timeout_minutes=timeout_minutes,
        )
        project.requires_network = bool(plan.get("requires_network", False))

        for step_data in plan["steps"]:
            project.steps.append(
                Step(
                    id=step_data["id"],
                    title=step_data["title"],
                    description=step_data["description"],
                    requires_approval=step_data.get("requires_approval", False),
                    status=StepStatus.PENDING,
                )
            )

        project.llm_calls += 1
        self._store.save_project(project)
        logger.info(
            "Project created",
            id=project.id,
            steps=len(project.steps),
            project_type=plan.get("project_type", "generic"),
            requires_network=project.requires_network,
        )
        return project

    def _add_quality_steps(self, plan: dict) -> dict:
        """Injecte une étape de test typée + RAPPORT.md en fin de plan."""
        project_type = plan.get("project_type", "generic")
        steps = plan["steps"]

        # Retire les doublons que le LLM aurait pu générer
        steps = [
            s
            for s in steps
            if "rapport" not in s.get("title", "").lower() and "test" not in s.get("id", "").lower()
        ]

        n = len(steps)
        test_step = self._add_test_step(project_type, step_num=n + 1)
        rapport_step = {
            "id": f"step_{n + 2:03d}",
            "title": "Générer RAPPORT.md",
            "description": (
                "Crée un fichier RAPPORT.md à la racine du workspace résumant : "
                "la liste des fichiers créés avec leurs tailles, les fonctionnalités "
                "implémentées, les tests effectués et leurs résultats, et les points "
                "d'amélioration éventuels. Format Markdown avec sections ## claires."
            ),
            "requires_approval": False,
        }

        steps.append(test_step)
        if project_type != "fusion_360":
            steps.append(rapport_step)
        plan["steps"] = steps
        return plan

    def _add_test_step(self, project_type: str, step_num: int) -> dict:
        """Retourne une étape de test adaptée au type de projet."""
        step_id = f"step_{step_num:03d}"

        if project_type == "website":
            return {
                "id": step_id,
                "title": "Vérification finale du site",
                "description": (
                    "1. Lister tous les fichiers HTML créés avec list_files. "
                    "2. Pour chaque HTML : vérifier que les CSS et JS référencés existent. "
                    "3. Si des fichiers manquent : les créer maintenant. "
                    "4. Vérifier que index.html existe à la racine. "
                    "5. Exécuter une validation syntaxique si possible."
                ),
                "requires_approval": False,
            }

        if project_type == "python_script":
            return {
                "id": step_id,
                "title": "Test du script Python",
                "description": (
                    "1. Exécuter le script principal avec python3 et des données de test. "
                    "2. Vérifier que le code de retour est 0. "
                    "3. Analyser stdout : la sortie est-elle cohérente avec l'objectif ? "
                    "4. Si erreur (returncode != 0) : lire stderr, corriger, relancer. "
                    "5. Ne pas continuer tant que le script ne tourne pas sans erreur."
                ),
                "requires_approval": False,
            }

        if project_type == "content":
            return {
                "id": step_id,
                "title": "Relecture et cohérence",
                "description": (
                    "1. Lire chaque fichier créé avec read_file et vérifier qu'il n'est pas vide. "
                    "2. Vérifier la cohérence entre les fichiers (références croisées, etc.). "
                    "3. Vérifier que l'objectif initial de la mission est atteint. "
                    "4. Corriger toute incohérence détectée."
                ),
                "requires_approval": False,
            }

        if project_type == "fusion_360":
            return {
                "id": step_id,
                "title": "Vérification finale Fusion 360",
                "description": (
                    "1. Prendre un screenshot isométrique avec "
                    "fusion_360(action='read', query_type='screenshot',"
                    " direction='iso-top-right'). "
                    "2. Vérifier que la géométrie est visible et conforme à l'objectif. "
                    "3. Si problème détecté, utiliser fusion_360(action='undo') et corriger. "
                    "4. Prendre un screenshot final (direction='top') pour confirmer."
                ),
                "requires_approval": False,
            }

        # generic (défaut)
        return {
            "id": step_id,
            "title": "Vérification et validation",
            "description": (
                "1. Lister tous les fichiers créés avec list_files, vérifier qu'aucun n'est vide. "
                "2. Vérifier que l'objectif initial de la mission est atteint. "
                "3. Tester / exécuter les livrables principaux si applicable. "
                "4. Corriger tout problème détecté avant de passer à l'étape suivante."
            ),
            "requires_approval": False,
        }

    def _parse_plan(self, raw: str) -> dict:
        clean = re.sub(r"```json|```", "", raw).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error("Plan parse failed", error=str(e), raw=raw[:300])
            raise ValueError(f"Impossible de parser le plan LLM : {e}") from e
