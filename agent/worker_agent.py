"""WorkerAgent — exécute les étapes d'un projet avec un vrai tool_loop Anthropic."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from loguru import logger

from agent.file_tool import SandboxedFileTool
from agent.project_store import ProjectStore
from agent.quality_checker import QualityChecker
from agent.schemas import LogEntry, Project, ProjectStatus, Step, StepStatus
from agent.worker_cli import WorkerCLITool
from core.budget import BudgetGuard

_QUALITY_RULES_PATH = Path(__file__).parent.parent / "prompts" / "worker_system.md"
try:
    _QUALITY_RULES = _QUALITY_RULES_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    _QUALITY_RULES = ""

_WORKER_SYSTEM = """\
Tu es un agent autonome expert qui exécute une étape précise d'un projet dans un workspace isolé.

Outils disponibles :
- read_file(path) : lire un fichier du workspace
- write_file(path, content) : créer ou modifier un fichier
- list_files(directory) : lister les fichiers (directory optionnel, défaut ".")
- execute_cli(command, timeout?) : exécuter une commande shell (whitelist stricte)
- create_directory(path) : créer un répertoire
- fusion_360(action, ...) : contrôler Autodesk Fusion 360 (si le projet l'exige)
  - action="execute_script", script="..." : exécuter un script Python Fusion API
  - action="read", query_type="screenshot" : capturer la vue actuelle
  - action="undo" / action="redo"
  IMPORTANT : les scripts doivent contenir def run(context): et utiliser adsk.core/adsk.fusion.
  Fusion utilise les centimètres (3 cm → createByReal(3)). Vérifier avec un screenshot après.
  OBLIGATOIRE : chercher un doc avec bRepBodies.count > 0 et l'activer en début de script.
  Si aucun body trouvé, travailler sur l'actif — JAMAIS app.documents.add() !
  Ne jamais supposer que app.activeProduct est le bon document.
  INTERDIT : root.name, rootComponent.name (lecture seule), addNewComponent() (mode Part).
  Nommer avec body.name = "..." uniquement. Mode Pièce : travailler sur rootComponent.
  Shell : top_face = max(body.faces, key=lambda f: f.centroid.z) — jamais par index.
  Cut (CutFeatureOperation) : "Aucun corps cible" = sketch sur mauvais plan ou
    participantBodies absent. Sketch sur une face du body, pas xYConstructionPlane.
    inp.participantBodies = ObjectCollection contenant le body cible — OBLIGATOIRE.

Règles absolues :
- Exécute UNIQUEMENT l'étape demandée
- Pour les tâches Fusion 360 : utilise fusion_360, JAMAIS execute_cli
- Ne tente jamais d'accéder à des fichiers hors du workspace
- Si un outil échoue, analyse l'erreur et adapte-toi ou retourne une erreur claire
- Retourne UN RÉSUMÉ D'UNE LIGNE maximum — pas de markdown, pas de tableaux, pas de sections
- Ne relis pas les fichiers que tu viens de créer sauf si tu as besoin de leur contenu pour la suite
- Ne recrée pas des répertoires qui existent déjà
- Commence directement par l'action principale (write_file, execute_cli, fusion_360)
- INTERDIT : générer des rapports, tableaux markdown, ou analyses détaillées dans ta réponse finale

Contexte projet :
{context}
"""

_WORKER_TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Lire le contenu d'un fichier dans le workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin relatif au workspace"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Créer ou écraser un fichier dans le workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "Lister les fichiers dans un répertoire du workspace",
        "input_schema": {
            "type": "object",
            "properties": {"directory": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "execute_cli",
        "description": "Exécuter une commande shell (whitelist stricte). Retourne stdout/stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
    },
    {
        "name": "create_directory",
        "description": "Créer un répertoire dans le workspace",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "fusion_360",
        "description": (
            "Contrôle Autodesk Fusion 360 via MCP (port 27182). "
            "Utiliser pour toute tâche de modélisation 3D. "
            "Les scripts doivent contenir def run(context): et utiliser adsk.core/adsk.fusion. "
            "Unités : centimètres (3 cm → createByReal(3))."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["execute_script", "read", "undo", "redo"],
                    "description": "Action Fusion 360 à effectuer",
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Script Python Fusion API complet avec def run(context):"
                        " (requis pour execute_script)"
                    ),
                },
                "query_type": {
                    "type": "string",
                    "enum": ["screenshot", "document", "projects", "apiDocumentation"],
                    "description": "Type de lecture (pour action=read)",
                },
                "direction": {
                    "type": "string",
                    "enum": [
                        "current",
                        "front",
                        "back",
                        "top",
                        "bottom",
                        "left",
                        "right",
                        "iso-top-right",
                    ],
                    "description": "Direction caméra pour screenshot",
                },
                "name": {
                    "type": "string",
                    "description": "Terme de recherche pour query_type=document",
                },
            },
            "required": ["action"],
        },
    },
]


class _BudgetExceeded(Exception):
    """Levée quand le budget est épuisé — met le projet en pause au lieu de le tuer."""


class WorkerAgent:
    def __init__(
        self,
        project: Project,
        store: ProjectStore,
        broadcast_event: Callable[[dict], None],
        approval_callback: Callable[[str, str, str], Awaitable[bool]],
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        self._project = project
        self._store = store
        self._broadcast = broadcast_event
        self._approval_cb = approval_callback
        self._budget = budget_guard
        self._worker_id = uuid.uuid4().hex[:8]  # identifiant unique pour les claims
        self._file_tool = SandboxedFileTool(project.workspace_path)
        self._cli_tool = WorkerCLITool(project.workspace_path)
        self._docker = None
        self._killed = False
        self._quality = QualityChecker(project.workspace_path)
        self._pending_issues: list[str] = []
        self._files_snapshot: list[str] = []

    def kill(self) -> None:
        self._killed = True
        logger.info("WorkerAgent killed", project_id=self._project.id)

    async def _setup_environment(self) -> None:
        """Configure l'environnement d'exécution : Docker V2 ou direct V1."""
        from config.settings import settings

        if settings.docker_enabled:
            from agent.docker_executor import DockerExecutor

            available = await DockerExecutor.is_available()
            if not available:
                await self._log("warning", "Docker non disponible — fallback V1 direct")
                return
            network = "bridge" if self._project.requires_network else settings.docker_network
            self._docker = DockerExecutor(
                workspace_path=self._project.workspace_path,
                project_id=self._project.id,
                network=network,
            )
            await self._docker.start()
            self._cli_tool = WorkerCLITool(
                workspace_path=self._project.workspace_path,
                docker_executor=self._docker,
            )
            await self._log("info", f"Environnement Docker démarré ({settings.docker_base_image})")
        else:
            await self._log("info", "Environnement direct V1")

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        project = self._project
        project.status = ProjectStatus.RUNNING
        project.started_at = datetime.now()
        self._store.save_project(project)
        await self._log("info", f"Démarrage : {project.title}")
        self._push_update()

        await self._setup_environment()

        try:
            for step in project.steps:
                if step.status in (StepStatus.DONE, StepStatus.SKIPPED):
                    continue  # déjà complétée — on ne re-exécute pas
                if self._killed:
                    project.status = ProjectStatus.KILLED
                    break
                await self._execute_step(step)
                if step.status == StepStatus.FAILED:
                    project.status = ProjectStatus.FAILED
                    await self._log("error", f"Étape échouée : {step.title}")
                    break
            else:
                project.status = ProjectStatus.DONE
                project.completed_at = datetime.now()
                report = self._quality.generate_report()
                if report["valid"]:
                    await self._log(
                        "info",
                        f"✓ Qualité finale : {len(report['files'])} fichier(s), aucun problème",
                    )
                else:
                    await self._log(
                        "warning",
                        f"Qualité finale : {len(report['issues'])} problème(s) détecté(s)",
                    )
                    for issue in report["issues"][:5]:
                        await self._log("warning", issue)
                await self._log("info", "✓ Projet terminé avec succès")
                self._broadcast(
                    {
                        "type": "project_done",
                        "project_id": project.id,
                        "title": project.title,
                    }
                )
        except Exception as e:
            project.status = ProjectStatus.FAILED
            await self._log("error", f"Erreur inattendue : {e}")
        finally:
            if self._docker:
                await self._docker.stop()
            self._store.save_project(project)
            self._push_update()

    # ── Step execution ─────────────────────────────────────────────────────────

    async def _execute_step(self, step: Step) -> None:
        # Claim atomique — évite la double-exécution si plusieurs workers tournent
        if not self._store.claim_step(self._project.id, step.id, self._worker_id):
            await self._log(
                "warning",
                f"Étape déjà réclamée par un autre worker : {step.title}",
                step_id=step.id,
            )
            return

        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()
        self._store.save_project(self._project)
        await self._log("info", f"→ {step.title}", step_id=step.id)
        self._push_update()

        # Approbation humaine si nécessaire
        if step.requires_approval:
            step.status = StepStatus.WAITING_APPROVAL
            self._store.save_project(self._project)
            self._push_update()
            await self._log("approval", f"Approbation requise : {step.title}", step_id=step.id)

            approved = await self._approval_cb(self._project.id, step.id, step.description)

            if not approved:
                step.status = StepStatus.SKIPPED
                step.output = "Refusée par l'utilisateur."
                await self._log("info", f"Étape refusée : {step.title}", step_id=step.id)
                self._store.save_project(self._project)
                self._push_update()
                return

        # Exécution via LLM tool-loop
        self._files_snapshot = self._file_tool.list_files()
        is_fusion = (
            "fusion" in self._project.mission.lower() or "fusion" in self._project.title.lower()
        )
        try:
            result = await asyncio.wait_for(self._run_step_llm(step), timeout=300)
            step.status = StepStatus.DONE
            step.output = result
            step.completed_at = datetime.now()
            if not is_fusion:  # quality check inutile pour Fusion (pas de fichiers)
                await self._post_step_check(step)
            await self._log(
                "info", f"✓ {step.title}", step_id=step.id, data={"output": result[:300]}
            )
        except _BudgetExceeded:
            # Hard-stop budget : on met le projet en pause (reprise possible)
            await self._log(
                "warning", f"Budget épuisé — pause du projet : {step.title}", step_id=step.id
            )
            self._store.pause_for_budget(self._project, step.id)
            self._push_update()
            self._broadcast(
                {
                    "type": "budget_hard_stop",
                    "project_id": self._project.id,
                    "step_id": step.id,
                    "message": (
                        "Budget atteint — projet mis en pause."
                        " Reprise possible après recharge."
                    ),
                }
            )
            return  # on sort proprement sans marquer le step FAILED
        except TimeoutError:
            step.status = StepStatus.FAILED
            step.error = "Timeout (5 min) dépassé."
            await self._log("error", f"Timeout : {step.title}", step_id=step.id)
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            await self._log("error", f"Erreur : {step.title} — {e}", step_id=step.id)

        self._store.save_project(self._project)
        self._push_update()

    # ── LLM tool-loop ─────────────────────────────────────────────────────────

    async def _run_step_llm(self, step: Step) -> str:
        from config.settings import settings
        from llm.api import AnthropicProvider

        # Vérification budget avant l'appel LLM (estimation conservatrice : 0.02 USD / step)
        _est_usd = 0.02
        if self._budget is not None:
            global_ok = await self._budget.reserve("global", _est_usd)
            project_ok = await self._budget.reserve(f"project:{self._project.id}", _est_usd)
            if not global_ok or not project_ok:
                raise _BudgetExceeded(
                    f"Budget dépassé (global={'ok' if global_ok else 'stop'}, "
                    f"project={'ok' if project_ok else 'stop'})"
                )

        # Haiku pour le worker : 20x moins cher que Sonnet, largement suffisant
        llm = AnthropicProvider(
            max_tokens=1024,
            model=settings.voice_anthropic_model,  # claude-haiku-4-5-20251001
        )
        self._project.llm_calls += 1

        existing = self._file_tool.list_files()
        context = (
            f"Titre : {self._project.title}\n"
            f"Mission : {self._project.mission}\n"
            f"Fichiers existants : {', '.join(existing[:15]) or '(aucun)'}"
        )

        system = _WORKER_SYSTEM.format(context=context)
        prompt = (
            f"Étape à exécuter : {step.title}\n\n"
            f"Description : {step.description}\n\n"
            f"Exécute cette étape avec les outils disponibles et retourne un résumé concis."
        )
        if self._pending_issues:
            issues_text = "\n".join(f"  • {i}" for i in self._pending_issues[-5:])
            prompt += (
                f"\n\nProblèmes qualité détectés aux étapes précédentes"
                f" (à corriger) :\n{issues_text}"
            )
            self._pending_issues.clear()

        if _QUALITY_RULES:
            system += f"\n\n{_QUALITY_RULES}"

        result = await llm.tool_loop(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            tools=_WORKER_TOOLS,
            tool_executor=self._tool_executor,
            context=f"mission:{self._project.id}",
        )

        # Track files created
        self._project.files_created = self._file_tool.list_files()
        return result

    # ── Post-step quality check ───────────────────────────────────────────────

    async def _post_step_check(self, step: Step) -> None:
        issues = self._quality.check_step_output(self._files_snapshot)
        if issues:
            self._pending_issues.extend(issues)
            for issue in issues:
                await self._log("warning", f"QualityCheck: {issue}", step_id=step.id)
        else:
            await self._log("info", "✓ QualityCheck OK", step_id=step.id)
        self._files_snapshot = self._file_tool.list_files()

    # ── Tool executor ─────────────────────────────────────────────────────────

    async def _tool_executor(self, name: str, inputs: dict) -> str:
        try:
            if name == "read_file":
                content = self._file_tool.read_file(inputs["path"])
                await self._log(
                    "tool", f"read_file: {inputs['path']}", data={"chars": len(content)}
                )
                return content

            if name == "write_file":
                result = self._file_tool.write_file(inputs["path"], inputs["content"])
                await self._log(
                    "tool", f"write_file: {inputs['path']}", data={"chars": len(inputs["content"])}
                )
                return result

            if name == "list_files":
                files = self._file_tool.list_files(inputs.get("directory", "."))
                await self._log(
                    "tool",
                    f"list_files: {inputs.get('directory', '.')}",
                    data={"count": len(files)},
                )
                return json.dumps(files)

            if name == "create_directory":
                result = self._file_tool.create_directory(inputs["path"])
                await self._log("tool", f"create_directory: {inputs['path']}")
                return result

            if name == "execute_cli":
                cmd = inputs["command"]
                timeout = int(inputs.get("timeout", 60))
                await self._log("tool", f"execute_cli: {cmd[:60]}")
                res = await self._cli_tool.execute(cmd, timeout=timeout)
                if res["success"]:
                    return res["stdout"] or "(commande exécutée, pas de sortie)"
                return f"ERREUR (rc={res['returncode']}) : {res['stderr']}"

            if name == "fusion_360":
                from tools.fusion import FusionTool

                action = inputs.get("action", "")
                await self._log("tool", f"fusion_360: {action}", data={"inputs": str(inputs)[:120]})
                tool = FusionTool()
                result = await tool.execute(**inputs)
                if result.is_error:
                    await self._log("error", f"fusion_360 erreur: {result.content[:200]}")
                return result.content

            return f"Outil inconnu : {name}"

        except ValueError as e:
            # Sandbox violation
            await self._log("error", f"SANDBOX: {e}")
            return f"ACCÈS REFUSÉ : {e}"
        except Exception as e:
            await self._log("error", f"Tool error {name}: {e}")
            return f"Erreur : {e}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _log(
        self,
        level: str,
        message: str,
        step_id: str | None = None,
        data: dict | None = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            message=message,
            step_id=step_id,
            data=data,
        )
        self._store.append_log(self._project, entry)
        logger.debug("WorkerAgent log", level=level, msg=message[:80])

    def _push_update(self) -> None:
        self._broadcast(
            {
                "type": "project_update",
                "project_id": self._project.id,
                "status": self._project.status,
                "steps": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "status": s.status,
                        "requires_approval": s.requires_approval,
                        "output": s.output,
                        "error": s.error,
                    }
                    for s in self._project.steps
                ],
            }
        )
