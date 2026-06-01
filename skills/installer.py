"""Installation/désinstallation des skills depuis jarvis-skills."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
from loguru import logger

from skills.registry import SKILLS_INSTALLED_DIR, skill_registry

ENV_FILE = Path(".env")

SKILLS_REPO_RAW = "https://raw.githubusercontent.com/Grominet95/jarvis-skills/main"
SKILLS_INDEX_URL = f"{SKILLS_REPO_RAW}/index.json"

LOCAL_CATALOG = Path("skills/catalog.json")


class SkillInstaller:
    def _inject_env_vars(self, requires_env: list[str], skill_name: str) -> None:
        """Ajoute les variables requires_env manquantes dans .env avec valeur vide."""
        from dotenv import dotenv_values, set_key

        existing = dotenv_values(str(ENV_FILE)) if ENV_FILE.exists() else {}
        for key in requires_env:
            if key not in existing:
                set_key(str(ENV_FILE), key, "")
                logger.debug(f"Env var ajoutée pour {skill_name}: {key}")

    async def fetch_catalog(self) -> list[dict]:
        """
        Récupère le catalogue depuis GitHub.
        Fallback sur le catalogue local si inaccessible.
        """
        offline = False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(SKILLS_INDEX_URL)
                if r.status_code == 200:
                    skills = r.json().get("skills", [])
                else:
                    raise Exception(f"HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"Catalogue GitHub inaccessible: {e} — fallback local")
            skills = self._load_local_catalog()
            offline = True

        installed = {s["name"] for s in skill_registry.list_installed()}
        for skill in skills:
            skill["installed"] = skill["name"] in installed
            skill["offline"] = offline

        return skills

    def _load_local_catalog(self) -> list[dict]:
        if LOCAL_CATALOG.exists():
            return json.loads(LOCAL_CATALOG.read_text()).get("skills", [])
        return []

    async def install(self, skill_name: str) -> dict:
        """Télécharge et installe un skill depuis GitHub."""
        catalog = await self.fetch_catalog()
        skill_meta = next((s for s in catalog if s["name"] == skill_name), None)

        if not skill_meta:
            return {
                "success": False,
                "message": f"Skill '{skill_name}' introuvable dans le catalogue",
            }

        skill_dir = SKILLS_INSTALLED_DIR / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_meta.get("path", f"skills/{skill_name}")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{SKILLS_REPO_RAW}/{path}/skill.py")
                if r.status_code != 200:
                    raise Exception(f"skill.py introuvable (HTTP {r.status_code})")
                (skill_dir / "skill.py").write_text(r.text)

                r = await client.get(f"{SKILLS_REPO_RAW}/{path}/skill.yaml")
                if r.status_code == 200:
                    (skill_dir / "skill.yaml").write_text(r.text)

            # Inject missing env vars + download static files from skill.yaml
            yaml_path = skill_dir / "skill.yaml"
            if yaml_path.exists():
                import yaml

                with yaml_path.open() as f:
                    meta = yaml.safe_load(f) or {}
                requires_env = meta.get("requires_env", [])
                if requires_env:
                    self._inject_env_vars(requires_env, skill_name)

                static_files = meta.get("static_files", [])
                if static_files:
                    static_dst = Path("ui/static/skills") / skill_name
                    static_dst.mkdir(parents=True, exist_ok=True)
                    async with httpx.AsyncClient(timeout=15) as client:
                        for fname in static_files:
                            r = await client.get(f"{SKILLS_REPO_RAW}/{path}/static/{fname}")
                            if r.status_code == 200:
                                (static_dst / fname).write_bytes(r.content)
                                logger.debug(f"Fichier statique installé : {fname}")
                            else:
                                logger.warning(
                                    f"Fichier statique manquant : {fname} (HTTP {r.status_code})"
                                )

            skill_registry.reload()
            logger.info(f"Skill installé : {skill_name}")
            return {"success": True, "message": f"Skill '{skill_name}' installé avec succès"}

        except Exception as e:
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            logger.error(f"Erreur installation {skill_name}: {e}")
            return {"success": False, "message": str(e)}

    def uninstall(self, skill_name: str) -> dict:
        """Désinstalle un skill."""
        skill_dir = SKILLS_INSTALLED_DIR / skill_name

        if not skill_dir.exists():
            return {"success": False, "message": f"Skill '{skill_name}' n'est pas installé"}

        try:
            shutil.rmtree(skill_dir)
            # Supprimer les fichiers statiques s'il y en a
            static_dst = Path("ui/static/skills") / skill_name
            if static_dst.exists():
                shutil.rmtree(static_dst)
                logger.debug(f"Fichiers statiques supprimés pour {skill_name}")
            skill_registry.reload()
            logger.info(f"Skill désinstallé : {skill_name}")
            return {"success": True, "message": f"Skill '{skill_name}' désinstallé"}
        except Exception as e:
            return {"success": False, "message": str(e)}


skill_installer = SkillInstaller()
