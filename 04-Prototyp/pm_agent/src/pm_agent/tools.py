"""The two tools Claude plans with. Both take the plan itself as input and run the
deterministic `planning.check_plan`, so Claude sees the same errors and warnings as the
project lead and corrects the plan itself.
"""

from typing import Any

from anthropic import beta_tool
from anthropic.lib.tools import ToolError
from pydantic import ValidationError

from pm_agent.models import CheckResult, Member, Plan, Project
from pm_agent.planning import check_plan

# The schedule stays out: it is long, and the warnings already name late tasks.
REPORTED = {"errors", "warnings", "end_date", "critical_path", "load"}


class PlanningTools:
    """The tools of one planning run. `plan` is set when submit_plan accepts a plan."""

    def __init__(self, project: Project, team: list[Member]) -> None:
        self.project = project
        self.team = team
        self.plan: Plan | None = None
        self.check_plan = beta_tool(
            self._check,
            name="check_plan",
            description=(
                "Prüft einen Planentwurf deterministisch. Liefert Fehler, Warnungen, Enddatum, "
                "kritischen Pfad und die Auslastung je Person bis zur Deadline."
            ),
            input_schema=Plan,
        )
        self.submit_plan = beta_tool(
            self._submit,
            name="submit_plan",
            description=(
                "Reicht den fertigen Plan bei der Projektleitung ein. Lehnt einen Plan mit "
                "Fehlern ab und nennt die Gründe. Warnungen hindern die Einreichung nicht."
            ),
            input_schema=Plan,
        )

    def _check(self, **plan: Any) -> str:
        return self._review(plan)[1].model_dump_json(include=REPORTED)

    def _submit(self, **plan: Any) -> str:
        parsed, result = self._review(plan)
        if result.errors:
            raise ToolError(
                "Plan abgelehnt. Behebe diese Fehler und reiche ihn erneut ein:\n"
                + "\n".join(f"- {error}" for error in result.errors)
            )
        self.plan = parsed
        return "Plan angenommen."

    def _review(self, data: dict[str, Any]) -> tuple[Plan | None, CheckResult]:
        try:
            plan = Plan.model_validate(data)
        except ValidationError as err:
            errors = [
                f"Ungültige Eingabe bei {'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in err.errors()
            ]
            return None, CheckResult(errors=errors)
        return plan, check_plan(plan, self.team, self.project)
