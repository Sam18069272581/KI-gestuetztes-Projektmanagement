# PM-Agent

KI-Agent für die Planungsphase von Softwareprojekten: Aufgaben zerlegen, Aufwand schätzen,
nach Skills und Verfügbarkeit zuweisen, Terminplan und Risiken ableiten. Die Projektleitung
prüft und entscheidet.

Stand: Planungskern (Datenmodell und deterministische Prüfung), Agent mit Laufprotokoll und
Streamlit-Oberfläche.

## Oberfläche

```bash
cd 04-Prototyp/pm_agent
uv run --env-file .env streamlit run app.py
```

Sechs Schritte als Reiter:

1. **Team**: Personen mit Skills (z. B. `Python 4, SQL 3`) und Wochenstunden; lokal speichern
   in `data/team.json`. Ohne Zustimmung des Teams startet keine Planung.
2. **Projekt**: Idee, Start, Deadline.
3. **Planung**: Claude plant, jede Runde erscheint sofort. Alternativ einen protokollierten Lauf
   aus `logs/` öffnen, ohne Claude erneut aufzurufen (z. B. für Vorführungen).
4. **Ergebnis**: Planende, Fehler, Warnungen, Gantt-Diagramm, Auslastung, Begründungen, Risiken.
5. **Anpassen**: Tabelle ändern und erneut prüfen; nur die deterministische Prüfung, kein LLM.
6. **Export**: Markdown oder CSV. Jeder Export wird mit Dauer und Änderungen in `logs/runs.csv`
   vermerkt, als Datengrundlage für den Vorher-nachher-Vergleich.

## Agent

`run_planning(project, team)` in `src/pm_agent/agent.py`: Claude entwirft den Plan, prüft ihn
mit dem Werkzeug `check_plan` (die deterministische Prüfung) und korrigiert ihn, bis
`submit_plan` ihn ohne Fehler annimmt. Warnungen (Überlastung, Deadline, fehlende Skills)
bleiben für die Projektleitung stehen. Liegt nach 10 Runden kein gültiger Plan vor, hört Claude
ohne Plan auf oder wird eine Antwort abgeschnitten oder abgelehnt, bricht der Agent mit einer
`PlanningError` ab.

Zugang: `.env.example` nach `.env` kopieren und `ANTHROPIC_API_KEY` eintragen. Das Modell
lässt sich mit `PM_AGENT_MODEL` ändern (Standard `claude-opus-5-5`).

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/).

```bash
cd 04-Prototyp/pm_agent
uv sync
uv run ruff check .
uv run pytest
```

Der Test gegen die echte API kostet Geld und dauert einige Minuten. Ohne `ANTHROPIC_API_KEY`
wird er übersprungen. Mit dem Key aus `.env`:

```bash
uv run --env-file .env pytest tests/test_agent_live.py
```

## Datenschutz

Das Repository ist öffentlich. Teamdaten (`data/`), Protokolle (`logs/`) und `.env` bleiben
lokal und sind per `.gitignore` ausgeschlossen.

Der Agent schickt Projektidee und Teamdaten (Namen, Skills, Wochenstunden, Notizen) an die
Anthropic API. Teammitglieder müssen vorher zustimmen.
