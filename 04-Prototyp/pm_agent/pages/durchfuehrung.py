"""Page "Durchführung": record progress per task and fill project documents from templates."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent.tracking import (
    PROGRESS_COLUMNS,
    STATUSES,
    apply_rows,
    evaluate,
    progress_rows,
    save,
    status_report,
    work_packages,
)
from pm_agent.ui import adopted_project
from pm_agent.workbench import InputError

state = st.session_state

st.header("Durchführung")
st.caption(
    "Fortschritt erfassen und Projektdokumente aus Vorlagen füllen. Diese Seite rechnet nur mit "
    "dem übernommenen Plan und deinen Angaben; es wird kein LLM aufgerufen."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
st.caption(
    f"Projekt: {tracking.project.idea} · übernommen am {tracking.adopted:%d.%m.%Y %H:%M} · "
    f"{len(tracking.plan.tasks)} Aufgaben"
)

st.subheader("Fortschritt")
if state.pop("progress_saved", False):
    st.success("Fortschritt gespeichert (lokal in data/projekt.json, nicht im Repository).")
edited = st.data_editor(
    pd.DataFrame(progress_rows(tracking), columns=PROGRESS_COLUMNS),
    # A new key after saving: the editor starts again from the saved state.
    key=f"progress_editor_{state.get('progress_version', 0)}",
    hide_index=True,
    width="stretch",
    disabled=PROGRESS_COLUMNS[:5],
    column_config={
        "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
        "Ist (h)": st.column_config.NumberColumn(min_value=0.0, step=0.5),
    },
)
st.caption("Änderungen gelten erst nach dem Speichern.")
if st.button("Fortschritt speichern", type="primary"):
    try:
        updated = apply_rows(tracking, edited.to_dict("records"))
    except InputError as err:
        st.error(f"Bitte korrigieren:\n\n{err}")
    else:
        save(updated)
        state.progress_saved = True
        state.progress_version = state.get("progress_version", 0) + 1
        st.rerun()

st.subheader("Dokumente aus Vorlagen")
st.caption("Gefüllt aus dem übernommenen Plan und dem gespeicherten Fortschritt.")
documents = {
    "Statusbericht": ("statusbericht", status_report(tracking, evaluate(tracking, date.today()))),
    "Arbeitspaketbeschreibungen": ("arbeitspakete", work_packages(tracking)),
}
chosen = st.radio("Vorlage", list(documents), horizontal=True)
file_stem, text = documents[chosen]
st.download_button(
    f"{chosen} als Markdown herunterladen",
    text,
    file_name=f"{file_stem}-{date.today():%Y%m%d}.md",
    mime="text/markdown",
)
with st.container(border=True):
    st.markdown(text)
