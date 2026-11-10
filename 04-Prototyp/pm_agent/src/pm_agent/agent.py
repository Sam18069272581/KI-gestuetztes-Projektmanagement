"""The planning agent. Claude drafts a plan, checks it with the deterministic tools and
corrects it until submit_plan accepts it. The project lead reviews the result.
"""

import json
import os
from contextlib import closing
from pathlib import Path

from anthropic import Anthropic

from pm_agent.models import Member, Plan, Project
from pm_agent.tools import PlanningTools

DEFAULT_MODEL = "claude-opus-5-5"
# One round is one reply from Claude. Drafting, a few checks and the submission take about
# five; ten without an accepted plan means Claude is stuck.
MAX_ROUNDS = 10
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "planning.md").read_text(encoding="utf-8")

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


def run_planning(project: Project, team: list[Member]) -> Plan:
    """Let Claude plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate."""
    tools = PlanningTools(project, team)
    runner = Anthropic().beta.messages.tool_runner(
        model=os.environ.get("PM_AGENT_MODEL") or DEFAULT_MODEL,
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
            details = message.stop_details
            raise_for_stop_reason(message.stop_reason, details.category if details else None)
            runner.generate_tool_call_response()  # runs the tools now; the runner reuses the result
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


def _request(project: Project, team: list[Member]) -> str:
    members = json.dumps([m.model_dump() for m in team], ensure_ascii=False, indent=2)
    return (
        f"Projekt:\n{project.model_dump_json(indent=2)}\n\nTeam:\n{members}\n\n"
        "Erstelle den Plan, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
