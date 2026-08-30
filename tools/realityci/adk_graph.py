"""RealityCI workflow executed ON Google ADK.

The durable campaign loop is exposed as an ADK SequentialAgent whose nodes
wrap the verified orchestrator steps.  Running it through InMemoryRunner
exercises real ADK graph execution, event streaming, and session-state
persistence without requiring any network model access — deterministic by
construction.  Requires `google-adk` (see .venv-realityci overlay env).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event
from google.adk.events.event_actions import EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .state_machine import TERMINAL_STATES, CampaignState


ADK_VERSION_INSTALLED = "google-adk/2.7.1"
APP_NAME = "servo-realityci"

PIPELINE: tuple[CampaignState, ...] = (
    CampaignState.PENDING,
    CampaignState.BASELINE_RUNNING,
    CampaignState.FAILURE_TRIAGE,
    CampaignState.DIAGNOSING,
    CampaignState.EXPERIMENTING,
    CampaignState.ROOT_CAUSE_GATE,
    CampaignState.CURRICULUM_PLANNING,
    CampaignState.TRAINING,
    CampaignState.HIDDEN_EXAM,
    CampaignState.REGRESSION_CHECK,
    CampaignState.PROMOTION_GATE,
    CampaignState.REALITY_DEBT_UPDATE,
)


def build_engine_factory(engine_kwargs: dict) -> Callable[[], object]:
    """Bind construction of the engine so ADK nodes stay serializable-ish."""

    def factory():
        from .orchestrator import CampaignEngine

        return CampaignEngine(**engine_kwargs)

    return factory


class StepNode(BaseAgent):
    """One ADK node = one verified orchestrator step."""

    expected_state: str
    engine_kwargs: dict = {}
    _engine: object | None = None

    def _resolve_engine(self):
        if self._engine is None:
            factory = build_engine_factory(self.engine_kwargs)
            self._engine = factory()
        return self._engine

    async def _run_async_impl(self, ctx) -> "asyncio.AsyncGenerator[Event, None]":
        import json

        engine = self._resolve_engine()
        current = engine.current_state()

        if current in TERMINAL_STATES:
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={
                    "realityci.skipped": self.name,
                    "realityci.last_state": current.value,
                    "realityci.campaign_id": engine.campaign_id,
                }),
            )
            return

        if _index(current) > _index(CampaignState(self.expected_state)):
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={
                    "realityci.skipped": self.name,
                }),
            )
            return

        if current != CampaignState(self.expected_state):
            raise RuntimeError(
                f"ADK node {self.name} expected {self.expected_state}, found {current.value}"
            )

        new_state = await asyncio.to_thread(engine.step_once)
        trace = list(ctx.session.state.get("realityci.steps", []))
        trace.append({"node": self.name, "to": new_state.value})
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={
                "realityci.steps": trace,
                "realityci.last_state": new_state.value,
                "realityci.campaign_id": engine.campaign_id,
            }),
        )


def _index(state: CampaignState) -> int:
    return PIPELINE.index(state)


def build_realityci_graph(engine_kwargs: dict) -> SequentialAgent:
    nodes = [
        StepNode(
            name=f"step_{i:02d}_{state.value}",
            description=f"RealityCI step {state.value}",
            expected_state=state.value,
            engine_kwargs=engine_kwargs,
        )
        for i, state in enumerate(PIPELINE)
    ]
    return SequentialAgent(name="RealityCILoop", sub_agents=nodes)


@dataclass
class AdkRunResult:
    terminal_state: CampaignState
    steps: list[dict]
    adk_event_count: int
    session_id: str


async def run_graph_async(
    engine_kwargs: dict,
    session_service: InMemorySessionService | None = None,
    session_id: str | None = None,
) -> AdkRunResult:
    graph = build_realityci_graph(engine_kwargs)
    service = session_service or InMemorySessionService()
    runner = Runner(agent=graph, app_name=APP_NAME, session_service=service)

    existing = await service.get_session(app_name=APP_NAME, user_id="servo", session_id=session_id or "")
    if existing is None:
        await service.create_session(app_name=APP_NAME, user_id="servo", session_id=session_id)

    adk_events = 0
    from google.genai import types as genai_types

    kickoff = genai_types.Content(
        role="user", parts=[genai_types.Part(text="run the realityci pipeline")]
    )
    async for _event in runner.run_async(
        user_id="servo", session_id=session_id, new_message=kickoff
    ):
        adk_events += 1

    session = await service.get_session(app_name=APP_NAME, user_id="servo", session_id=session_id)
    last = session.state.get("realityci.last_state")
    terminal = CampaignState(last) if last in {s.value for s in TERMINAL_STATES} else None
    if terminal is None:
        raise RuntimeError(f"ADK graph ended non-terminal: {last!r}")
    return AdkRunResult(
        terminal_state=terminal,
        steps=list(session.state.get("realityci.steps", [])),
        adk_event_count=adk_events,
        session_id=session_id,
    )


def run_campaign_on_adk(root: Path, baseline_checkpoint_path: Path, **engine_overrides) -> AdkRunResult:
    """Synchronous convenience entrypoint used by CLI/tests."""

    kwargs = {"root": Path(root), "baseline_checkpoint_path": Path(baseline_checkpoint_path)}
    kwargs.update(engine_overrides)
    session_id = "servo-" + root.name
    return asyncio.run(run_graph_async(kwargs, session_id=session_id))
