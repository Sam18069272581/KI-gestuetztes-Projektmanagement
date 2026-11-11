import csv
import io
import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import Member, Plan
from pm_agent.planning import check_plan
from pm_agent.workbench import (
    InputError,
    append_run,
    load_run,
    load_team,
    plan_rows,
    round_summary,
    rows_to_plan,
    rows_to_team,
    save_team,
    saved_runs,
    team_rows,
    to_csv,
    to_markdown,
)

PLAN = Plan.model_validate(plan_input())


def test_team_table_round_trip_and_skill_formats():
    rows = [
        {"Name": "Anna", "Skills": "Python 4, SQL:3", "Stunden/Woche": 20, "Notiz": None},
        {"Name": None, "Skills": None, "Stunden/Woche": None, "Notiz": None},  # empty editor row
    ]
    team = rows_to_team(rows)
    assert team == [Member(name="Anna", skills={"Python": 4, "SQL": 3}, hours_per_week=20)]
    assert rows_to_team(team_rows(team)) == team


def test_unreadable_team_rows_name_the_row_and_the_problem():
    rows = [
        {"Name": "Anna", "Skills": "Python sehr gut", "Stunden/Woche": 20},
        {"Name": "Ben", "Skills": "", "Stunden/Woche": 0},
    ]
    with pytest.raises(InputError) as err:
        rows_to_team(rows)
    message = str(err.value)
    assert "Zeile 1 (Anna): Skill 'Python sehr gut' nicht lesbar" in message
    assert "Zeile 2 (Ben): hours_per_week" in message


def test_plan_table_round_trip_keeps_descriptions_and_risks():
    original = Plan.model_validate(
        {
            **plan_input(),
            "tasks": [{**plan_input()["tasks"][0], "description": "Tabellen"}]
            + plan_input()["tasks"][1:],
        }
    )
    rebuilt = rows_to_plan(plan_rows(original), original, original.risks)
    assert rebuilt == original


def test_an_edit_in_the_table_reaches_the_check():
    rows = plan_rows(PLAN)
    rows[0]["Stunden"] = 400  # far beyond Anna's capacity until the deadline
    edited = rows_to_plan(rows, PLAN, PLAN.risks)
    assert any("überlastet" in w for w in check_plan(edited, TEAM, PROJECT).warnings)


def test_a_row_without_person_stays_unassigned_and_the_check_says_so():
    rows = plan_rows(PLAN)
    rows[1]["Person"] = ""
    result = check_plan(rows_to_plan(rows, PLAN, []), TEAM, PROJECT)
    assert result.errors == ["Task 'B' ist niemandem zugewiesen"]


def test_an_invalid_estimate_is_an_input_error():
    rows = plan_rows(PLAN)
    rows[0]["Stunden"] = -3
    with pytest.raises(InputError, match="Zeile 1 \\(A\\): estimate_hours"):
        rows_to_plan(rows, PLAN, [])


def test_team_file_round_trip_missing_file_and_damaged_file(tmp_path):
    path = tmp_path / "data" / "team.json"
    assert load_team(path) == []
    save_team(TEAM, path)
    assert load_team(path) == TEAM
    path.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(InputError, match="team.json ist beschädigt"):
        load_team(path)


def test_only_runs_with_plan_project_and_team_can_be_reopened(tmp_path):
    record = {
        "outcome": "plan",
        "project": PROJECT.model_dump(mode="json"),
        "team": [m.model_dump(mode="json") for m in TEAM],
        "plan": PLAN.model_dump(mode="json"),
        "rounds": [],
    }
    (tmp_path / "run-20261111-090000.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "run-20261111-080000.json").write_text(
        json.dumps({**record, "plan": None, "outcome": "error"}), encoding="utf-8"
    )
    (tmp_path / "run-20261110-080000.json").write_text(  # logged before project/team were kept
        json.dumps({"outcome": "plan", "plan": record["plan"]}), encoding="utf-8"
    )

    (path,) = saved_runs(tmp_path)
    project, team, plan, _ = load_run(path)
    assert (project, team, plan) == (PROJECT, TEAM, PLAN)


def test_runs_csv_gets_one_header_and_one_line_per_export(tmp_path):
    path = tmp_path / "logs" / "runs.csv"
    append_run({"quelle": "agent", "runden": 3}, path)
    append_run({"quelle": "protokoll", "runden": 0}, path)
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [
        {"quelle": "agent", "runden": "3"},
        {"quelle": "protokoll", "runden": "0"},
    ]


def test_round_summary_counts_check_messages_and_names_rejections():
    report = check_plan(PLAN, TEAM, PROJECT).model_dump_json(include={"errors", "warnings"})
    checked = {"tool_results": [{"tool": "check_plan", "is_error": False, "content": report}]}
    rejected = {
        "tool_results": [
            {
                "tool": "submit_plan",
                "is_error": True,
                "content": "Plan abgelehnt. Behebe diese Fehler:\n- X",
            }
        ]
    }
    accepted = {
        "tool_results": [{"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}]
    }

    assert round_summary(1, checked) == (
        "Runde 1 · check_plan: 0 Fehler, 1 Warnungen",
        ["Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben"],
    )
    assert round_summary(2, rejected) == (
        "Runde 2 · submit_plan: abgelehnt",
        ["Plan abgelehnt. Behebe diese Fehler:\n- X"],
    )
    assert round_summary(3, accepted) == ("Runde 3 · submit_plan: Plan angenommen.", [])
    assert round_summary(4, {"text": "", "stop_reason": "end_turn"})[0] == (
        "Runde 4 · beendet (end_turn)"
    )


def test_export_contains_dates_reasons_and_warnings():
    result = check_plan(PLAN, TEAM, PROJECT)
    markdown = to_markdown(PROJECT, PLAN, result)
    assert (
        "| A | Datenmodell | Anna | 8 | 09.11.2026 | 09.11.2026 | kennt die Raumdaten |" in markdown
    )
    assert "**Kritischer Pfad:** A → B" in markdown
    assert "- Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben" in markdown
    assert "- Die Hochschule liefert die Raumdaten zu spät" in markdown

    rows = list(csv.reader(io.StringIO(to_csv(PLAN, result)), delimiter=";"))
    assert rows[0][-3:] == ["Start", "Ende", "Begründung"]
    assert rows[2][:3] == ["B", "API", "Anna"] and rows[2][-3:-1] == ["10.11.2026", "11.11.2026"]
    assert result.end_date == date(2026, 11, 11)
