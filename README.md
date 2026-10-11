# Terminally Chill

A free, no-login web app that forecasts how crowded parts of an airport will be and recommends quiet places to rest near your gate. You enter a gate and a boarding time. It shows ranked rest spots, a "leave by" countdown, a walking route on a terminal map, and a crowd forecast you can scrub through.

Terminally Chill is built to work for any airport. **This version covers one: Hartsfield-Jackson Atlanta International Airport (ATL), Concourse B only (gates B1-B39).** See [Other airports](#other-airports) for what adding another one takes.

Built at Hacklanta '26 (Georgia State University, Oct 9-11, 2026). Live demo: https://terminallychill.us

Crowd levels are estimates computed from flight schedules, not measurements. See [Limitations](#limitations) before relying on any number here.

## Why we built it

Anyone who has flown knows how hard it is to find a place to rest on a long layover. For stranded, budget, disabled, or young-family travelers, it is an access problem.

Airports show where gates and restrooms are, not which areas are quiet right now. The alternatives are static reviews or paid pods and lounges, often far from your gate. Many people end up sleeping next to their gate for fear of missing the flight. We wanted a free, gate-aware tool so you can rest without that worry.

## What it does

In this version, for ATL Concourse B:

1. You type a gate (for example `B12`) and a boarding time in Atlanta local time.
2. The server forecasts crowding in each part of the concourse for the time between now and boarding.
3. It ranks the rest areas by how crowded they will be while you wait, minus a penalty for walking time.
4. For the top pick it shows when you must leave to be back at the gate with a safety buffer, and draws the route.

An optional photo box lets someone near the gate send one photo. A person counter estimates how many people are in it, and that corrects the forecast for that area for 30 minutes (see [Person counter](#person-counter-optional)).

## How the forecast works

The model is a simple passenger-flow estimate. It is a pure function in `app/model.py`: flights in, forecast out, no database.

- **Where people are.** Each departing flight with a gate in Concourse B puts `seats x load factor` passengers into that gate's zone. Seats come from the aircraft type (`data/seats_by_type.json`); a missing type uses a default of 150 seats.
- **When they arrive.** Passengers arrive between 90 and 10 minutes before departure on a triangular curve that peaks 40 minutes before departure. Departure time is the estimated time if the provider has one, otherwise scheduled time plus delay.
- **Amenities.** 35% of passengers spend 20 minutes at food or shops, split by a gravity weight (attractiveness divided by walking time plus 60 s). The rest stay in the gate zone until 10 minutes before departure.
- **Cancellations.** 30% of a cancelled flight's passengers go to the customer-service zone for 60 minutes.
- **Index.** People in a zone divided by the zone's capacity, times 100, limited to 0-100. Forecasts use 5-minute buckets.

The ranking is in `app/ranking.py`. For each rest area it finds the shortest walk from your gate zone, then:

```
leave_by    = boarding - walk back - 10 min buffer
stay        = leave_by - (now + walk there)           must be at least 10 min
stay_crowd  = 0.6 x mean crowd + 0.4 x peak crowd, over the stay
score       = 100 - stay_crowd - 3 x walking minutes
```

A rest area takes its crowd from the nearest gate zone. Higher score ranks first. If no spot leaves enough time, the response says so instead of returning a poor pick.

Gate assignments change. Every recommendation carries that warning.

## API

Everything is served by one FastAPI app. In this version the endpoints cover ATL Concourse B. All times in requests and responses are UTC ISO-8601 (`...Z`). The page displays Atlanta time.

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Always 200 while the process is up. Reports `db: true/false`. |
| `GET /api/summary?hours=2` | Departures per concourse for the next `hours` (counts only). |
| `GET /api/graph` | The Concourse B walking graph used by the model. |
| `GET /api/assumptions` | Every tunable parameter with its value and unit. |
| `GET /api/forecast?concourse=B&start=...&hours=3` | Crowd index per zone in 5-minute buckets. `hours` is 0-12 and must be a whole number of buckets. |
| `GET /api/recommend?gate=B12&boarding=...&limit=3` | Ranked rest spots, leave-by times, routes. A gate outside B returns `supported: false`. |
| `POST /api/photo` | Optional. Multipart `zone_id` and `image`. Returns the count and the adjusted index. |
| `POST /api/ask` | Optional. JSON `{"text": "..."}`. Needs a Gemini key. Not used by the page. |

Forecast and recommendation responses include `data_source: {provider, pulled_at, synthetic}`. `synthetic: true` means the numbers came from the invented sample, and the page labels it SAMPLE DATA.

Example (PowerShell, boarding in 90 minutes):

```powershell
$b = (Get-Date).ToUniversalTime().AddMinutes(90).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
curl.exe -s "https://terminallychill.us/api/recommend?gate=B12&boarding=$b"
```

The public API never returns flight-level records. It returns counts, crowd indexes and recommendations.

## Data sources

| Source | Use | Notes |
|---|---|---|
| FlightAware AeroAPI (`aeroapi`) | Default real data: scheduled departures at ATL (ICAO `KATL`) | 15 flights per result page. On the plan used for the demo, each page cost about 1 cent. |
| Aviationstack (`aviationstack`) | Alternative provider | Free tier is non-commercial. It does not report aircraft type, so seats fall back to the default. |
| Synthetic sample (`snapshot`) | Development and offline demo | 223 invented flights (idents start with `ZZ`) in `data/sample/atl_synthetic.json`. The only flight data committed to this repo. |

Rules the code follows:

- **Visitors never call the flight provider.** A scheduled ingest job pulls flights into the database, and the public API reads only from there.
- **One provider per run.** Data from different providers is never merged. Switch with `FLIGHT_PROVIDER` or `--provider`.
- **Hard page cap.** Every ingest run stops at a maximum number of result pages, so a run has a known maximum cost.
- **Raw data is not committed.** Raw provider pages are saved to `data/raw/` (git-ignored) and deleted after 30 days. A TimescaleDB retention policy (`sql/002_timescale.sql`) drops flight rows after 30 days. `python -m app.initdb` applies it on Tiger Data and skips it, with a warning, on plain PostgreSQL.
- **AeroAPI terms.** The Personal tier is for personal and academic use. That is why raw data is capped at 30 days and why the public API returns only derived results.
- **Concourse comes from the gate.** The concourse is the first letter of the gate. The provider's terminal field (N/S) is stored as metadata only.

## Privacy

There are no accounts and no sign-in.

- **No tracking.** The page loads no third-party scripts, fonts, analytics or CDNs. It uses no cookies and no browser storage. The only links to other sites are the Google Maps and Apple Maps buttons, which open only when you tap them and send only the airport's name.
- **No request logs.** The app server runs with access logging off, and the reverse-proxy config has no log block. Hosting-provider infrastructure logs are outside this repo's control.
- **Photos are not stored.** A photo is decoded and counted in memory and is never saved or logged. One caveat: the web framework holds uploads over 1 MB in a temporary file and deletes it when the request ends. The photo is never sent to any other service.
- **Photo counts are anonymous.** The server keeps only `(timestamp, zone, count)` in memory for 30 minutes. It has no database table, so a restart clears it.
- **The database holds flight schedules only.** There is no table that refers to a user.
- **Ask feature.** If you enable it, the single typed sentence is sent to Google's Gemini API, so Google receives that text. Nothing else is sent, and the page does not use this feature.
- **Secrets.** API keys and the database URL live only in environment variables. `.env` is git-ignored.

## Assumptions

All defaults are in `app/assumptions.py` and are served by `GET /api/assumptions`. **None of them is measured.** They are starting points chosen from how airports generally work.

| Parameter | Default | Meaning |
|---|---|---|
| `load_factor` | 0.85 | Share of seats filled |
| `arrive_min_before_dep` | 90 min | Earliest arrival at the gate |
| `arrival_peak_min_before_dep` | 40 min | Peak of the arrival curve |
| `boarding_closes_min_before_dep` | 10 min | When passengers leave the gate area |
| `default_seats` | 150 | Seats when aircraft type is unknown |
| `amenity_share` | 0.35 | Share visiting food or shops |
| `amenity_dwell_min` | 20 min | Time spent there |
| `amenity_gravity_constant_s` | 60 s | Walk-time constant in the amenity weight |
| `cancellation_pax_fraction` | 0.3 | Cancelled passengers who go to customer service |
| `cancellation_dwell_min` | 60 min | How long they stay |
| `leave_buffer_min` | 10 min | Safety buffer before boarding |
| `min_stay_min` | 10 min | Shortest wait worth recommending |
| `walk_penalty_per_min` | 3.0 points | Score lost per walking minute |
| `stay_mean_weight` | 0.6 | Weight on average crowd versus peak crowd |

Other inputs that are estimates, not measurements:

- **Seat counts** (`data/seats_by_type.json`) are typical counts, mostly for Delta, with sources noted in the file. Real layouts vary by about 20%.
- **Walking times and zone capacities** (`data/atl_graph.json`) were estimated by hand from an original schematic (`web/concourse.svg`). They are not measured and not an official map.

## Sensitivity check

`scripts/sensitivity.py` re-runs the forecast with one assumption changed at a time and reports whether the zone order and the top rest spot for gate B12 change.

```bash
python -m scripts.sensitivity
```

Output on the synthetic sample (3-hour forecast, Concourse B):

| Change | Top zone by peak index | Zones that changed rank | Top rest spot for gate B12 |
|---|---|---|---|
| Baseline (load factor 0.85) | B-food-1 | n/a | B-rest-mid |
| Load factor 0.70 | B-food-1 | 0 | B-rest-mid |
| Load factor 0.95 | B-food-1 | 0 | B-rest-mid |
| Seats -20% | B-food-1 | 0 | B-rest-mid |
| Seats +20% | B-food-1 | 0 | B-rest-mid |
| Arrival peak 25 min before departure | B-food-1 | 0 | B-rest-mid |
| Arrival peak 70 min before departure | B-food-1 | 0 | B-rest-mid |

**How to read this.** Nothing moved, but that is weaker evidence than it looks. In the baseline run, six of the ten zones reach the index cap of 100 for 75 to 135 of the 180 minutes (the four gate zones, food and shops). Once a zone is capped, changing load factor or seats cannot change its ranking. So the table shows that these variations do not reorder a mostly capped index. It does not show that the forecast is right. There is no ground-truth crowd data for ATL to compare against, and the zone capacities and walking times were not varied.

## Person counter (optional)

`POST /api/photo` counts people in one photo with a MobileNet-SSD detector (OpenCV's DNN module, trained on PASCAL VOC, "person" class, confidence at least 0.5). The weight files are not in this repo. Their source and license are recorded in `data/models/SOURCE.md` (listed there as MIT).

- Limits: 5 MB per upload, 40 megapixels per image. Larger uploads are rejected.
- The correction for a zone is `photo count / model's people estimate for that zone`, limited to 0.5-2.0, and it fades linearly back to 1.0 over 30 minutes. Only the newest count per zone is used.
- `app/counts.py` holds the in-memory counts. `forecast(..., zone_multipliers=...)` in `app/model.py` applies them.

**No accuracy number is reported.** `scripts/eval_counter.py` compares the counter with hand-counted photos and prints mean absolute error and bias, but it does not download pictures or invent counts. To produce a number:

1. Collect public crowd photos with permissive licenses into `data/eval/photos/`.
2. Count the people in each by hand.
3. Write `data/eval/hand_counts.json` using `data/eval/hand_counts.example.json` as the template (each photo needs `file`, `count`, `url`, `license`).
4. Run `python scripts/eval_counter.py`.

Both `data/eval/photos/` and `hand_counts.json` are git-ignored.

## Ask endpoint (optional)

`POST /api/ask` turns one typed sentence such as "nap near B12, I board in 2 hours" into a gate and a number of hours, then runs the same ranking as `/api/recommend`.

- The sentence is at most 500 characters and is the only thing sent to Gemini. The explanation in the reply is built from our own ranking numbers, not from the model's text, so the model cannot invent a crowd index.
- The model's reply is checked before use: the gate must parse and the hours must be between 0 and 12. Anything else returns 422.
- Without `GEMINI_API_KEY` the endpoint returns 503 "not configured" and the rest of the app is unaffected.
- The page does not call this endpoint yet.

## Limitations

- **ATL Concourse B only, in this version.** Other concourses and other airports are not modeled. A gate outside B returns `supported: false`.
- **The crowd index is an estimate from schedules.** It is not noise, and it is not a live sensor reading. Walking times, zone capacities and every assumption above are unmeasured, and nothing here has been validated against real crowds.
- **The index saturates.** It is limited to 0-100, and busy zones sit at 100 for long stretches. Two zones at 100 look identical even when one is far busier, which reduces how much the crowd term can separate spots.
- **Gates change.** The forecast uses the gate the provider reports. Flights with no gate cannot be placed in a zone, and the API reports how many (`unassigned_flights`).
- **Data is only as fresh as the last ingest.** The page shows when data was pulled, but nothing warns you when it is old.
- **Photo counts are crude.** A photo shows only part of a zone but is compared with the model's estimate for the whole zone, so a photo can pull a zone's index down even when the zone is busy (a photo with nobody in it halves the index). Anyone can submit a photo, and the newest count wins. Counts live in one process and reset on restart.
- **No rate limiting or authentication** on the public endpoints.
- **Single small server.** One VM, one app process.
- **Not an official airport tool.** Check the airport's monitors for gate changes and boarding times.

## Other airports

The crowd model and the ranking are not specific to Atlanta. They take a walking graph and a list of flights and return a forecast, so nothing in `app/model.py` or `app/ranking.py` names ATL. The Atlanta-specific parts of this version are data and configuration:

- **A terminal map.** A walking graph (zones, walking times, capacities) and a schematic, as in `data/atl_graph.json` and `web/concourse.svg`. Each one is hand-estimated, and the loader reads one concourse per file.
- **A flight-data feed.** A provider module in `app/providers/` that returns departures with gates for that airport. Coverage, licensing and cost differ between providers, so this is the harder part.
- **Airport settings.** The airport codes and time zone, set as constants in `app/config.py` (currently `ATL`, `KATL`, `America/New_York`), plus the gate-to-concourse rule.

None of this has been done for a second airport, so treat multi-airport support as the design goal, not a tested feature.

Planned, not built: package the service as a container (the repo has no Dockerfile yet) that an airport operator could deploy, using its own on-premise flight data in place of a commercial feed.

## Run it locally

Requires Python 3.10 or newer and a PostgreSQL connection string (a free Tiger Data service, or a local PostgreSQL).

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env        # then set DATABASE_URL in .env
python -m app.initdb
python -m app.ingest --provider snapshot
uvicorn app.main:app --reload
```

Bash:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # then set DATABASE_URL in .env
python -m app.initdb
python -m app.ingest --provider snapshot
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. With the snapshot provider the page shows a SAMPLE DATA badge. To look at the page with no database at all, open `/?mock=1`. It is labeled demo mode and calls no API.

Real data needs `AEROAPI_KEY` and one small first run to see the page count and cost:

```bash
python -m app.ingest --purge snapshot          # remove the synthetic rows first
python -m app.ingest --provider aeroapi --hours 2 --max-pages 1
```

`--dry-run` fetches and parses without writing to the database, but it still calls the provider and still costs a page.

To enable the photo counter, download the two files listed in `data/models/SOURCE.md` into `data/models/` and set `PERSON_MODEL_DIR=data/models`.

## Configuration

Settings come from environment variables only. A local `.env` is read for convenience.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none | PostgreSQL / Tiger Data connection string |
| `FLIGHT_PROVIDER` | `aeroapi` | `aeroapi`, `aviationstack` or `snapshot` |
| `AEROAPI_KEY` | none | AeroAPI key |
| `AVIATIONSTACK_KEY` | none | Aviationstack key |
| `AEROAPI_MAX_PAGES` | 3 | Page cap per ingest run when `--max-pages` is not given |
| `AVIATIONSTACK_MAX_PAGES` | 3 | Same, for Aviationstack |
| `RAW_DIR` | `data/raw` | Where raw provider pages are saved |
| `PERSON_MODEL_DIR` | none | Folder with the MobileNet-SSD files. Unset disables `/api/photo`. |
| `GEMINI_API_KEY` | none | Enables `/api/ask`. Server side only. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model id |
| `TEST_DATABASE_URL` | none | Throwaway database for the database tests. **The `flights` table is dropped.** |

The default page cap of 3 is about 45 flights, which is far less than the forecast needs. Raise it with `--max-pages` (roughly 15 to 19 pages covers a 4-hour window at ATL; check the `pages` line of your first run).

## Deploy

The demo runs on a small Ubuntu VM on Google Cloud:

- **Caddy** terminates HTTPS (automatic certificates) and proxies to the app (`deploy/Caddyfile`; replace `YOUR_DOMAIN`).
- **systemd** runs the app as an unprivileged user (`deploy/airport-rest-finder.service`, uvicorn with `--no-access-log`).
- **Secrets** are in a root-only environment file (`/etc/airport-rest-finder/env`, mode 600) that systemd loads.
- **Database** is a Tiger Data service. The VM's address may need to be on its allow list.
- **Refresh** is `deploy/airport-ingest.service` plus an optional `deploy/airport-ingest.timer` (every 30 minutes). Every run spends up to its page cap, so enable the timer only after you know the per-page cost.

To update a running server:

```bash
cd /opt/airport-rest-finder
sudo -u appuser git pull --ff-only origin main
sudo -u appuser .venv/bin/pip install -r requirements.txt
sudo systemctl restart airport-rest-finder
curl -s http://127.0.0.1:8000/healthz
```

A healthy server answers `{"ok":true,"db":true}`.

## Tests

```bash
python -m pytest -q
```

Currently 56 pass and 3 are skipped. The skipped tests need `TEST_DATABASE_URL` (see the warning above). Use `python -m pytest`, not bare `pytest`, so the repo root is on the import path.

## Repository layout

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI app, `/healthz`, `/api/summary`, static page |
| `app/routes/` | One module per endpoint group |
| `app/model.py` | Crowd forecast (pure function) |
| `app/ranking.py` | Rest-spot ranking and leave-by |
| `app/assumptions.py` | Tunable parameters and seat lookup |
| `app/graph.py` | Walking graph loader and shortest paths |
| `app/counts.py`, `app/vision.py` | In-memory photo counts and the person detector |
| `app/nl.py` | Gemini sentence parsing for `/api/ask` |
| `app/providers/` | One module per flight-data source |
| `app/ingest.py`, `app/initdb.py`, `app/db.py`, `app/repo.py` | Ingest, schema setup, database access |
| `sql/` | Schema and TimescaleDB steps |
| `data/atl_graph.json`, `data/seats_by_type.json` | Hand-estimated graph and seat table |
| `data/sample/` | Synthetic flights (the only flight data in git) |
| `data/models/SOURCE.md` | Source and license of the detector files (files not committed) |
| `scripts/sensitivity.py`, `scripts/eval_counter.py` | Sensitivity table and counter accuracy check |
| `web/` | The page: `index.html`, `app.js`, `style.css`, `concourse.svg` |
| `deploy/` | Caddyfile and systemd units |
| `tests/` | Test suite |

## Lessons from the build

- **Flight data is the foundation, and it was the hardest part.** The forecast is only as good as the schedule behind it, and providers differ in coverage, licensing and cost. Choosing a source took longer than any other task, which is why the code keeps one provider per run and caps the pages each run can spend.
- **The ideal architecture is bigger than a weekend.** A highly available, distributed service was out of reach for a small team in a short time. This version is one VM and one app process (see [Limitations](#limitations)).
- **Lived experience shaped the design.** The problem came from what it is like to wait in an airport, and the features follow from that: free, no account, nothing stored about you, and honest about what the numbers can and cannot say.

## Built with

Python, FastAPI, uvicorn, psycopg, OpenCV (MobileNet-SSD person detector), PostgreSQL with TimescaleDB on Tiger Data, Caddy, FlightAware AeroAPI, and Google's Gemini API (optional, text only). The page is plain HTML, CSS and JavaScript with no frameworks and no external requests. It is deployed on a Google Cloud VM with systemd and Caddy.
