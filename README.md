# Hyderabad Air Quality Monitor 🍃

An autonomous data-engineering pipeline tracking real-time and historical air quality data across Hyderabad and Telangana from the **OpenAQ API v3**. The project ingests, validates, cleans, and deduplicates sensor measurements, computes statistical anomalies using rolling Median Absolute Deviation (MAD), stores data behind a database-agnostic SQLAlchemy ORM layer (PostgreSQL production storage with SQLite local fallback), and serves analytics via an interactive Streamlit dashboard.

---

## Live Dashboard

🔗 **Live Streamlit App**: [https://hyderabad-air-quality-monitor.streamlit.app/](https://hyderabad-air-quality-monitor.streamlit.app/)

---

## End-to-End System Architecture

```mermaid
flowchart LR
    subgraph S1["1. Data Source"]
        OpenAQ["OpenAQ API v3\n(TSPCB Telemetry)"]
    end

    subgraph S2["2. Pipeline Engine (Python 3.12+)"]
        Client["API Client & Rate Limiter"]
        Pipeline["Ingestion, Validation & Transform"]
        Anomaly["Rolling MAD Anomaly Detection"]
        Client --> Pipeline --> Anomaly
    end

    subgraph S3["3. Storage (SQLAlchemy ORM)"]
        PG[("PostgreSQL\n(Supabase Cloud)")]
        SQLite[("SQLite\n(Local Fallback)")]
        Migrate["scripts/migrate_sqlite_to_postgres.py"]
        SQLite -. Idempotent Sync .-> Migrate --> PG
    end

    subgraph S4["4. Presentation & CI/CD"]
        GHA["GitHub Actions\n(07:00 IST Scheduled Run)"]
        Streamlit["Streamlit Cloud\n(Interactive Dashboard)"]
    end

    OpenAQ --> Client
    Pipeline --> PG
    Pipeline --> SQLite
    PG --> Streamlit
    GHA -. Triggers Daily .-> Pipeline
```

---

## Project Metrics (Verified from Live Database)

> [!NOTE]
> All metrics below reflect verified output from live pipeline runs directly queried via `python scripts/generate_metrics.py`:

| Metric | Measured Value |
|---|---|
| **Monitoring Stations Tracked** | `21` (TSPCB & regional stations) |
| **Sensors Mapped** | `273` sensors |
| **Total Telemetry Collected** | `10,262` records |
| **Active Time Horizon** | `3.5 days` (2026-10-11 00:30 UTC to 2026-10-14 12:00 UTC) |
| **Total Rows Processed** | `10,717` records |
| **Missing-Data / Rejection Rate** | `0.00%` (0 invalid/malformed records) |
| **Statistical Anomalies Flagged** | `148` readings (Rolling MAD > 3.5, $\ge 48$ obs) |
| **Pipeline Workflow Runs** | `3` executions |
| **Workflow Success Rate** | `100.0%` |
| **Automated Test Suite** | `27 passed` (100% pass rate) |

---

## Data Source Attribution

- **Primary Provider**: [OpenAQ API v3](https://docs.openaq.org/)
- **Upstream Origin**: Telangana State Pollution Control Board (TSPCB), Central Pollution Control Board (CPCB), India.
- **License / Terms**: Open data accessed via OpenAQ API under open data terms. Measurements represent official monitoring station telemetry.

---

## Tech Stack

- **Language**: Python 3.12+ (compatible with Python 3.14)
- **API & Networking**: `requests`, urllib3 with exponential backoff on HTTP 429/5xx
- **Data Manipulation**: `pandas`, `numpy`
- **Database & ORM**: `SQLAlchemy 2.x`, `psycopg2-binary` (PostgreSQL production backend with native `ON CONFLICT DO UPDATE` upserts; SQLite fallback)
- **Dashboard**: `Streamlit`, `Plotly`
- **Testing**: `pytest` (mocked unit tests, live smoke tests, and PostgreSQL integration tests)
- **CI/CD Automation**: GitHub Actions (`daily_pipeline.yml`)

---

## Database Schema & Migration

- **`locations`**: `id` (PK), `name`, `latitude`, `longitude`, `country`, `timezone`, `owner_name`, `source_metadata`, `created_at_utc`.
- **`sensors`**: `id` (PK), `location_id` (FK), `parameter`, `unit`, `display_name`.
- **`measurements`**: `id` (PK), `sensor_id` (FK), `location_id` (FK), `parameter`, `value` (normalized), `unit` (normalized), `value_original`, `unit_original`, `measured_at_utc`, `ingested_at_utc`, `source`, `quality_flag`.
  - **Unique Constraint**: `(sensor_id, parameter, measured_at_utc)` ensures ingestion idempotency.
  - **Indexes**: `measured_at_utc` and `(location_id, parameter)`.
- **`ingestion_runs`**: `id` (PK), `started_at`, `finished_at`, `status`, `requests_made`, `rows_received`, `rows_inserted`, `rows_updated`, `rows_rejected`, `quality_report`, `error_message`.
- **`anomalies`**: `id` (PK), `sensor_id` (FK), `location_id` (FK), `parameter`, `measured_at_utc`, `observed_value`, `baseline_median`, `expected_low`, `expected_high`, `method`, `severity`, `detected_at_utc`.

### SQLite to PostgreSQL Migration
To migrate local records from `data/airquality.db` to your production PostgreSQL database:
```powershell
python scripts/migrate_sqlite_to_postgres.py --target-url "postgresql://user:pass@host:5432/dbname?sslmode=require"
```
The script runs in batches, reports row counts before and after, synchronizes serial sequences, and is safe to re-run.

---

## Local Setup

### 1. Clone & Set Up Environment

```powershell
# Clone the repository
git clone https://github.com/mahendravelagapudi099-wq/hyderabad-air-quality-monitor.git
cd hyderabad-air-quality-monitor

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install pinned dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Edit `.env` to configure your keys:

```ini
OPENAQ_API_KEY=your_openaq_api_key_here
# Use PostgreSQL or leave default SQLite for local development:
DATABASE_URL=sqlite:///data/airquality.db
# DATABASE_URL=postgresql://username:password@ep-host.region.aws.neon.tech/neondb?sslmode=require
```

*(Get a free API key at [explore.openaq.org/register](https://explore.openaq.org/register)).*

---

## Run Commands

### Run Daily Ingestion Pipeline (3-Day Rolling Window)
```powershell
python scripts/run_pipeline.py --days 3
```

### Backfill Historical Data (Up to 30 Days)
```powershell
python scripts/backfill.py --days 30
```

### Check Station Coverage
```powershell
python scripts/check_coverage.py
```

### Generate Real Metrics Output
```powershell
python scripts/generate_metrics.py
```

### Launch Streamlit Dashboard
```powershell
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

### Run Automated Tests
```powershell
pytest tests/ -v
```

---

## Streamlit Community Cloud Deployment

1. **Push your code to GitHub**:
   ```powershell
   git push origin main
   ```
2. **Log in to [share.streamlit.io](https://share.streamlit.io/)**:
   - Click **"Create app"**.
   - Select your repository: `hyderabad-air-quality-monitor`.
   - Branch: `main` (or `master`).
   - Main file path: `app.py`.
3. **Configure Secrets**:
   - In App Settings -> **Secrets**, paste:
     ```toml
     OPENAQ_API_KEY = "your_real_openaq_api_key"
     DATABASE_URL = "postgresql://user:password@host:5432/dbname?sslmode=require"
     ```
   *(See [`.streamlit/secrets.toml.example`](file:///.streamlit/secrets.toml.example) for reference).*
4. **Deploy**:
   - Click **Deploy**. Streamlit Cloud will install `requirements.txt` and launch the app.

---

## GitHub Actions & Scheduled Automation

The scheduled pipeline is configured in [`.github/workflows/daily_pipeline.yml`](file:///.github/workflows/daily_pipeline.yml):
- **Schedule**: `30 1 * * *` (01:30 UTC = 07:00 IST daily) and manual `workflow_dispatch`.
- **Secrets Required**:
  - `OPENAQ_API_KEY`: OpenAQ API Key.
  - `DATABASE_URL`: Production PostgreSQL connection string.
- **Permissions**: `contents: read` (safe and non-destructive).

### Workflow Keep-Alive & Inactivity Protection
> [!IMPORTANT]
> GitHub automatically disables scheduled workflows on repositories that have had no commit activity for 60 days.  
> The workflow includes a scheduled health check step. To keep scheduled workflows permanently active on GitHub:
> - Push periodic commits, or
> - Manually trigger `workflow_dispatch` once every 60 days if the repo is inactive.

---

## Troubleshooting

1. **`ModuleNotFoundError: No module named 'psycopg2'`**:
   - Ensure you installed `requirements.txt` which includes `psycopg2-binary==2.9.13`.
2. **PostgreSQL URI `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`**:
   - The application automatically normalizes legacy `postgres://` URIs to `postgresql://`. If connecting manually, ensure the URI starts with `postgresql://`.
3. **SSL Connection Issues on Hosted Postgres (Neon / Supabase / AWS)**:
   - Ensure your connection string includes `?sslmode=require`.
4. **GitHub Actions Secret Missing**:
   - Verify secrets are set in repository: **Settings** -> **Secrets and variables** -> **Actions** -> `OPENAQ_API_KEY` and `DATABASE_URL`.

---

## Dashboard Screenshots

### 1. Overview & Automated Insights
Real-time KPI metric gauges, regional station coverage summaries, and deterministic telemetry narratives.

<img src="docs/screenshots/overview_insights.png" width="720" alt="Overview & Automated Insights" />

### 2. Pollutant Trends
Interactive Plotly multi-station time-series segregating particulate matter ($\text{PM}_{2.5}$ & $\text{PM}_{10}$ in $\mu\text{g/m}^3$) and gaseous pollutants.

<img src="docs/screenshots/pollutant_trends.png" width="720" alt="Pollutant Trends" />

### 3. Station Comparisons
Comparative mean pollutant concentrations across all active Telangana monitoring stations.

<img src="docs/screenshots/station_comparisons.png" width="720" alt="Station Comparisons" />

### 4. Interactive Data Explorer
Filterable tabular view by station, parameter, quality flag, and timeframe with one-click CSV export.

<img src="docs/screenshots/data_explorer.png" width="720" alt="Data Explorer" />

### 5. Flagged Statistical Anomalies
Mathematical outliers detected using rolling Median Absolute Deviation ($\text{MAD} > 3.5$, $\ge 48$ historical observations guardrail) categorized by severity.

<img src="docs/screenshots/statistical_anomalies.png" width="720" alt="Statistical Anomalies" />

### 6. Pipeline Health & Quality Audits
Execution logs, throughput history, zero rejection verification, and automated data quality audits.

<img src="docs/screenshots/pipeline_health.png" width="720" alt="Pipeline Health" />
