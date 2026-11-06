import pytest

from pm_agent.agent import PlanningError, raise_for_stop_reason


@pytest.mark.parametrize(
    "stop_reason, category, message",
    [
        ("max_tokens", None, "Die Antwort von Claude wurde abgeschnitten"),
        ("model_context_window_exceeded", None, "passt nicht mehr ins Kontextfenster"),
        ("refusal", None, r"Claude hat die Anfrage abgelehnt\."),
        ("refusal", "cyber", r"Claude hat die Anfrage abgelehnt \(Kategorie: cyber\)"),
    ],
)
def test_a_reply_that_cannot_lead_to_a_plan_is_an_error(stop_reason, category, message):
    # The SDK's tool runner just stops on these, so a missing check would end the run silently.
    with pytest.raises(PlanningError, match=message):
        raise_for_stop_reason(stop_reason, category)


@pytest.mark.parametrize("stop_reason", ["tool_use", "end_turn"])
def test_regular_replies_pass(stop_reason):
    raise_for_stop_reason(stop_reason, None)
