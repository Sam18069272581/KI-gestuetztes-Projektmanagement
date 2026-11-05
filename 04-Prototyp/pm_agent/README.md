# PM-Agent

KI-Agent für die Planungsphase von Softwareprojekten: Aufgaben zerlegen, Aufwand schätzen,
nach Skills und Verfügbarkeit zuweisen, Terminplan und Risiken ableiten. Die Projektleitung
prüft und entscheidet.

Stand: Planungskern (Datenmodell und deterministische Prüfung). Agent und Oberfläche folgen.

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/).

```bash
cd 04-Prototyp/pm_agent
uv sync
uv run ruff check .
uv run pytest
```

## Datenschutz

Das Repository ist öffentlich. Teamdaten (`data/`) und Protokolle (`logs/`) bleiben lokal und
sind per `.gitignore` ausgeschlossen.
