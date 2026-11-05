from datetime import date

import pytest

from pm_agent.models import Assignment, Member, Plan, Project, Task
from pm_agent.planning import add_workdays, check_plan, count_workdays

MON = date(2026, 11, 9)
ANNA = Member(name="Anna", skills={"Python": 4}, hours_per_week=40)  # 8 h per workday
BEN = Member(name="Ben", skills={"React": 3}, hours_per_week=40)


def project(start=MON, deadline=date(2026, 12, 18)):
    return Project(idea="Lernplattform für Erstsemester", start_date=start, deadline=deadline)


def task(tid, hours, deps=(), skills=()):
    return Task(
        id=tid,
        title=f"Task {tid}",
        estimate_hours=hours,
        depends_on=list(deps),
        required_skills=list(skills),
    )


def plan(*tasks, owners):
    assignments = [Assignment(task_id=t, member=m, reason="passt") for t, m in owners.items()]
    return Plan(tasks=list(tasks), assignments=assignments)


def by_id(result):
    return {s.task_id: s for s in result.schedule}


def test_workday_helpers_skip_weekends():
    fri, sat, sun = date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)
    assert add_workdays(fri, 0) == fri
    assert add_workdays(fri, 1) == date(2026, 11, 16)
    assert add_workdays(sat, 0) == date(2026, 11, 16)
    assert count_workdays(MON, sun) == 5
    assert count_workdays(sun, MON) == 0


def test_chain_for_one_member_runs_back_to_back():
    p = plan(task("A", 8), task("B", 16, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    result = check_plan(p, [ANNA], project())
    assert result.ok
    assert result.warnings == []
    assert (by_id(result)["A"].start, by_id(result)["A"].end) == (MON, MON)
    assert (by_id(result)["B"].start, by_id(result)["B"].end) == (
        date(2026, 11, 10),
        date(2026, 11, 11),
    )
    assert result.end_date == date(2026, 11, 11)
    assert result.critical_path == ["A", "B"]


def test_members_work_in_parallel_and_critical_path_follows_the_longer_branch():
    p = plan(
        task("A", 8),
        task("B", 16),
        task("C", 8, deps=["A", "B"]),
        owners={"A": "Anna", "B": "Ben", "C": "Anna"},
    )
    result = check_plan(p, [ANNA, BEN], project())
    assert by_id(result)["A"].start == by_id(result)["B"].start == MON
    assert by_id(result)["C"].start == date(2026, 11, 11)  # waits two days for B
    assert result.critical_path == ["B", "C"]


def test_one_member_does_one_task_at_a_time_and_that_wait_is_on_the_critical_path():
    p = plan(task("A", 16), task("B", 8), owners={"A": "Anna", "B": "Anna"})
    result = check_plan(p, [ANNA], project())
    assert by_id(result)["B"].start == date(2026, 11, 11)
    assert result.critical_path == ["A", "B"]


def test_part_time_member_takes_longer():
    clara = Member(name="Clara", hours_per_week=10)  # 2 h per workday
    result = check_plan(plan(task("A", 5), owners={"A": "Clara"}), [clara], project())
    assert result.schedule[0].end == date(2026, 11, 11)  # 2.5 workdays: Mon to Wed


def test_float_noise_does_not_shift_the_end_date():
    # 7 h/week = 1.4 h/day, so each 2.1 h task takes 1.5 days. The float sum is
    # 3.0000000000000004; a plain ceil would end on Thursday instead of Wednesday.
    clara = Member(name="Clara", hours_per_week=7)
    p = plan(task("A", 2.1), task("B", 2.1, deps=["A"]), owners={"A": "Clara", "B": "Clara"})
    assert check_plan(p, [clara], project()).end_date == date(2026, 11, 11)


def test_overload_and_missed_deadline_are_warnings_not_errors():
    clara = Member(name="Clara", hours_per_week=10)  # 10 h available until Friday
    p = plan(task("A", 15), owners={"A": "Clara"})
    result = check_plan(p, [clara], project(deadline=date(2026, 11, 13)))
    assert result.ok
    assert result.load[0].utilization == pytest.approx(1.5)
    # 15 h at 2 h/day = 7.5 workdays: ends Wed 18.11., three workdays after Fri 13.11.
    assert result.end_date == date(2026, 11, 18)
    assert result.warnings == [
        "Der Plan endet am 18.11.2026, 3 Arbeitstage nach der Deadline (13.11.2026)",
        "Clara ist überlastet: 15 h zugewiesen, bis zur Deadline sind 10 h verfügbar (150%)",
    ]


def test_missing_skill_is_a_warning_and_matching_ignores_case():
    p = plan(task("A", 8, skills=["python", "Docker"]), owners={"A": "Anna"})
    result = check_plan(p, [ANNA], project())
    assert result.warnings == [
        "Task 'A' braucht 'Docker', Anna hat diese Fähigkeit nicht angegeben"
    ]


def test_structural_errors_are_all_reported_and_stop_scheduling():
    p = Plan(
        tasks=[task("A", 8, deps=["X"]), task("A", 8), task("B", 8)],
        assignments=[
            Assignment(task_id="A", member="Anna", reason="passt"),
            Assignment(task_id="A", member="Anna", reason="passt"),
            Assignment(task_id="Z", member="Zoe", reason="passt"),
        ],
    )
    result = check_plan(p, [ANNA, ANNA], project())
    assert not result.ok
    assert result.schedule == []
    assert sorted(result.errors) == sorted(
        [
            "Der Name 'Anna' kommt im Team mehrfach vor",
            "Die Task-ID 'A' ist mehrfach vergeben",
            "Task 'A' hängt von der unbekannten Task 'X' ab",
            "Zuweisung für die unbekannte Task 'Z'",
            "Task 'Z' ist 'Zoe' zugewiesen, diese Person ist nicht im Team",
            "Task 'A' ist mehrfach zugewiesen",
            "Task 'B' ist niemandem zugewiesen",
        ]
    )


def test_cycle_is_reported_with_its_path():
    p = plan(task("A", 8, deps=["B"]), task("B", 8, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    [error] = check_plan(p, [ANNA], project()).errors
    prefix = "Zyklische Abhängigkeit: "
    assert error.startswith(prefix)
    assert set(error.removeprefix(prefix).split(" → ")) == {"A", "B"}


def test_self_dependency_is_a_cycle():
    p = plan(task("A", 8, deps=["A"]), owners={"A": "Anna"})
    assert check_plan(p, [ANNA], project()).errors == ["Zyklische Abhängigkeit: A → A"]


def test_no_workday_between_start_and_deadline_is_an_error():
    weekend = project(start=date(2026, 11, 14), deadline=date(2026, 11, 15))
    result = check_plan(plan(task("A", 8), owners={"A": "Anna"}), [ANNA], weekend)
    assert result.errors == [
        "Zwischen Start (14.11.2026) und Deadline (15.11.2026) liegt kein Arbeitstag"
    ]


def test_empty_team_is_an_error():
    result = check_plan(plan(task("A", 8), owners={"A": "Anna"}), [], project())
    assert "Das Team ist leer" in result.errors
