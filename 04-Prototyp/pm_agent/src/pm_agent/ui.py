"""Streamlit pieces that several pages share."""

import streamlit as st

from pm_agent.tracking import Tracking, load
from pm_agent.workbench import InputError


def adopted_project() -> Tracking | None:
    """The adopted project. Without one, the page shows why and gets None."""
    try:
        tracking = load()
    except InputError as err:
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
        return None
    if tracking is None:
        st.info(
            "Noch kein Projekt übernommen. Erstelle oder öffne einen Plan auf der Seite Planung "
            "und wähle dort im Schritt Export „Plan als Projekt übernehmen“."
        )
    return tracking
