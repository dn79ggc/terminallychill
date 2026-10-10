# Airport Rest Finder (ATL)

Forecasts ATL concourse crowding from flight schedules and gates, and recommends quiet spots near the traveler's gate.
Hacklanta '26 project. No login, no user accounts.

This repo currently contains **Tier A (foundation)**: flight-data ingestion, database, API, and a proof page.

## Layout

| Path | Purpose |
|---|---|
| `app/providers/` | One module per flight-data source (`aeroapi`, `aviationstack`, `snapshot`). Exactly one is used per run; data is never merged. |
| `app/ingest.py` | Pull pages (hard page cap) -> save raw -> parse -> upsert into the database |
| `app/initdb.py` | Applies `sql/*.sql` |
| `app/main.py` | FastAPI: `/healthz`, `/api/summary`, static `web/` |
| `data/sample/` | **Synthetic** flights (invented). The only flight data that is committed. |
| `data/raw/` | Raw provider pages. Git-ignored, pruned after 30 days. |
| `deploy/` | Caddyfile and systemd units for the Vultr VM |

## Local quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env               # PowerShell: Copy-Item .env.example .env   then fill in DATABASE_URL
python -m app.initdb
python -m app.ingest --provider snapshot
uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Tests need a throwaway Postgres: `TEST_DATABASE_URL=postgresql://... pytest` (the `flights` table is dropped!).
Without it, the database tests are skipped.

## Data and privacy notes

- Real provider data is never committed. Keys live only in environment variables.
- The public API returns per-concourse counts only.
- Provider terms (AeroAPI Personal: personal/academic use, raw data <= 30 days, no mixing with other real-time providers)
  are why the ingest uses one provider per run and prunes raw files.
