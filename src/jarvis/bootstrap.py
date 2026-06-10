"""Composition root — CDC §C.1.

UNIQUE point d'instanciation du graphe d'objets de Jarvis. AUCUNE logique
métier ici : juste de la construction et du câblage.

Ordre strict de construction (CDC §C.1) :

    settings → bus → providers → capabilities → engine

Au point d'étape Phase C (1er motif d'injection), seuls les trois constructeurs
les plus légers sont construits par `build()` : BudgetGuard, UsageTracker,
SessionManager. Les autres (gateway, agent, mission, proactive, background,
process voix) seront ajoutés par itérations successives à mesure que leurs
constructeurs sont migrés.

NB : `build()` n'est PAS encore appelé par `src/jarvis/app.py` (qui continue
à instancier en direct). Le branchement vers le Container se fait après
validation manuelle du motif par Barth (cf. CDC §C contrat de validation —
« tests verts n'est PAS la gate de validation en Phase C »).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jarvis.kernel.events import EventBus
from jarvis.kernel.paths import MEMORY_DATA_DIR
from jarvis.kernel.settings import Settings
from jarvis.kernel.settings import settings as _default_settings

if TYPE_CHECKING:
    # Imports différés autorisés (TYPE_CHECKING) — pas de cycle, pas de coût runtime.
    from jarvis.engine.budget import BudgetGuard
    from jarvis.engine.session import SessionManager
    from jarvis.engine.tracking import UsageEntry, UsageTracker


@dataclass
class Container:
    """Graphe d'objets construit par `build()`.

    Étendu commit par commit au fil de Phase C. À la fin de C, ce Container
    contient le graphe COMPLET (providers, capabilities, engine).
    """

    settings: Settings
    bus: EventBus
    # ── Engine — premier batch (point d'étape Phase C) ─────────────────────
    tracker: UsageTracker
    budget: BudgetGuard
    session_manager: SessionManager


def build(settings: Settings | None = None) -> Container:
    """Construit le graphe d'objets dans l'ordre strict (CDC §C.1).

    `settings` injectable pour les tests (FakeSettings ou copie modifiée) ;
    par défaut, utilise le singleton `jarvis.kernel.settings.settings`.
    """
    # ── 1. Settings ────────────────────────────────────────────────────────
    if settings is None:
        settings = _default_settings

    # ── 2. Bus ─────────────────────────────────────────────────────────────
    bus = EventBus()

    # ── 3. Providers L1 ────────────────────────────────────────────────────
    # (Au point d'étape : seul SessionStore est construit ici, le strict
    #  nécessaire pour SessionManager. Les autres providers viendront.)
    from jarvis.providers.memory.sessions import SessionStore

    session_store = SessionStore(MEMORY_DATA_DIR / "sessions")

    # ── 4. Capabilities L1 ─────────────────────────────────────────────────
    # (Skippé au point d'étape.)

    # ── 5. Engine L2 — premier batch ───────────────────────────────────────
    from jarvis.engine.budget import BudgetGuard
    from jarvis.engine.session import SessionManager
    from jarvis.engine.tracking import UsageTracker

    # Two-phase setup pour casser le cycle BudgetGuard ↔ UsageTracker :
    #   - UsageTracker doit pouvoir notifier BudgetGuard de chaque entry mission.
    #   - BudgetGuard a besoin d'UsageTracker pour _seed_from_history() et
    #     _global_spent() (lecture des JSONL).
    # On construit tracker SANS callback, puis budget avec tracker, puis on
    # ré-attache le callback dans tracker. Pas d'instanciation interne, pas
    # d'import différé entre les deux fichiers — câblage explicite ici.
    tracker = UsageTracker(on_usage_callback=None)
    budget = BudgetGuard(settings=settings, tracker=tracker)
    tracker.set_on_usage_callback(_make_budget_callback(budget))

    session_manager = SessionManager(store=session_store)

    return Container(
        settings=settings,
        bus=bus,
        tracker=tracker,
        budget=budget,
        session_manager=session_manager,
    )


def _make_budget_callback(budget: BudgetGuard) -> Callable[[UsageEntry], None]:
    """Câble UsageTracker.track() → BudgetGuard.record() pour les coûts mission.

    Anciennement : tracking.py importait `get_budget_guard()` en local et
    appelait `guard.record(...)`. Cycle budget↔tracking interne à engine.
    Maintenant : le câblage vit ici, hors des deux modules.
    """

    def callback(entry: UsageEntry) -> None:
        if entry.cost_usd > 0 and entry.context and entry.context.startswith("mission:"):
            project_id = entry.context.split(":", 1)[1]
            budget.record(f"project:{project_id}", entry.cost_usd)

    return callback
