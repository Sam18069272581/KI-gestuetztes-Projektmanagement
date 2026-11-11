"""The planning agent. Claude drafts a plan, checks it with the deterministic tools and
corrects it until submit_plan accepts it. The project lead reviews the result.
"""

import json
import os
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from pm_agent.models import Member, Plan, Project
from pm_agent.tools import PlanningTools

DEFAULT_MODEL = "claude-opus-5-5"
# One round is one reply from Claude. Drafting, a few checks and the submission take about
# five; ten without an accepted plan means Claude is stuck.
MAX_ROUNDS = 10
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "planning.md").read_text(encoding="utf-8")
# 04-Prototyp/pm_agent/logs, next to the package and git-ignored: logs hold team data.
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

# The SDK's tool runner ends quietly on these replies. None of them can lead to a plan.
_STOP_ERRORS = {
    "max_tokens": (
        "Die Antwort von Claude wurde abgeschnitten, weil sie zu lang war. "
        "Beschreibe das Projekt knapper oder plane es in Teilen."
    ),
    "model_context_window_exceeded": (
        "Der Verlauf passt nicht mehr ins Kontextfenster von Claude. Starte die Planung neu."
    ),
}


class PlanningError(RuntimeError):
    """The agent produced no plan. The message is German and meant for the project lead."""


def run_planning(
    project: Project,
    team: list[Member],
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> Plan:
    """Let Claude plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate.
    Each run, successful or not, is written to `log_dir` as one JSON file (None: no log).
    `on_round` gets each round as soon as its tools have run, for live progress."""
    rounds: list[dict[str, Any]] = []
    plan: Plan | None = None
    error = None
    started = datetime.now().astimezone()
    try:
        plan = _run(project, team, rounds, on_round or (lambda _: None))
        return plan
    except Exception as err:
        error = f"{type(err).__name__}: {err}"
        raise
    finally:
        if log_dir is not None:
            _write_log(log_dir, started, project, team, rounds, plan, error)


def _run(
    project: Project,
    team: list[Member],
    rounds: list[dict[str, Any]],
    on_round: Callable[[dict[str, Any]], None],
) -> Plan:
    tools = PlanningTools(project, team)
    client = Anthropic()
    # The SDK checks credentials only when it sends, and then raises a bare TypeError.
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise PlanningError(
            "Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt. Trage den "
            "Schlüssel in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
        )
    runner = client.beta.messages.tool_runner(
        model=_model(),
        max_tokens=16_000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _request(project, team)}],
        tools=[tools.check_plan, tools.submit_plan],
        output_config={"effort": "high"},
        cache_control={"type": "ephemeral"},  # every round resends the history
        # On a refusal the API reruns the request on a fallback model it picks, in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        # Full history in every request: no conversation copy with team data stays on the server.
        thread=False,
        max_iterations=MAX_ROUNDS,
    )
    message = None
    with closing(runner):
        for message in runner:
            rounds.append(_round(message))
            details = message.stop_details
            raise_for_stop_reason(message.stop_reason, details.category if details else None)
            # Runs the tools now; the runner reuses the result for the next request.
            response = runner.generate_tool_call_response()
            rounds[-1]["tool_results"] = _tool_results(message, response)
            on_round(rounds[-1])
            if tools.plan is not None:
                return tools.plan
    if message is not None and message.stop_reason == "end_turn":
        said = " ".join(block.text for block in message.content if block.type == "text")
        raise PlanningError(f"Claude hat aufgehört, ohne einen Plan einzureichen. {said}".rstrip())
    raise PlanningError(f"Claude hat nach {MAX_ROUNDS} Runden noch keinen gültigen Plan.")


def raise_for_stop_reason(stop_reason: str | None, refusal_category: str | None) -> None:
    if stop_reason == "refusal":
        category = f" (Kategorie: {refusal_category})" if refusal_category else ""
        raise PlanningError(
            f"Claude hat die Anfrage abgelehnt{category}. Formuliere die Projektidee um."
        )
    if stop_reason in _STOP_ERRORS:
        raise PlanningError(_STOP_ERRORS[stop_reason])


def _model() -> str:
    return os.environ.get("PM_AGENT_MODEL") or DEFAULT_MODEL


def _round(message: Any) -> dict[str, Any]:
    """What Claude did in one reply. `model` can differ from the requested one after a
    refusal fallback."""
    return {
        "model": message.model,
        "stop_reason": message.stop_reason,
        "usage": message.usage.model_dump(exclude_none=True),
        "text": " ".join(b.text for b in message.content if b.type == "text"),
        "tool_calls": [
            {"name": b.name, "input": b.input} for b in message.content if b.type == "tool_use"
        ],
        "tool_results": [],
    }


def _tool_results(message: Any, response: dict[str, Any] | None) -> list[dict[str, Any]]:
    names = {b.id: b.name for b in message.content if b.type == "tool_use"}
    return [
        {
            "tool": names.get(result["tool_use_id"]),
            "is_error": bool(result.get("is_error")),
            "content": _text(result.get("content")),
        }
        for result in (response or {}).get("content", [])
    ]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content or [])


def _write_log(
    log_dir: Path,
    started: datetime,
    project: Project,
    team: list[Member],
    rounds: list[dict[str, Any]],
    plan: Plan | None,
    error: str | None,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"run-{started:%Y%m%d-%H%M%S}.json"
    record = {
        "started": started.isoformat(timespec="seconds"),
        "seconds": round((datetime.now().astimezone() - started).total_seconds(), 1),
        "requested_model": _model(),
        "outcome": "plan" if plan is not None else "error",
        "error": error,
        "project": project.model_dump(mode="json"),
        "team": [member.model_dump(mode="json") for member in team],
        "rounds": [{"round": n, **item} for n, item in enumerate(rounds, start=1)],
        "plan": plan.model_dump(mode="json") if plan is not None else None,
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _request(project: Project, team: list[Member]) -> str:
    members = json.dumps([m.model_dump() for m in team], ensure_ascii=False, indent=2)
    return (
        f"Projekt:\n{project.model_dump_json(indent=2)}\n\nTeam:\n{members}\n\n"
        "Erstelle den Plan, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
