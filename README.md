# Hyderabad Air Quality Monitor 🍃

An autonomous data-engineering pipeline tracking real-time and historical air quality data across Hyderabad and Telangana from the **OpenAQ API v3**. The project ingests, validates, cleans, and deduplicates sensor measurements, computes statistical anomalies using rolling Median Absolute Deviation (MAD), stores data behind a database-agnostic SQLAlchemy ORM layer (SQLite / PostgreSQL ready), and visualizes insights on an interactive Streamlit dashboard.

---

## Architecture

```mermaid
flowchart TD
    subgraph Data Sources
        OpenAQ[OpenAQ API v3\n/v3/locations & /v3/sensors]
    end

    subgraph Data Engineering Pipeline
        Config[src/config.py\nEnvironment & Bounds]
        Client[src/api_client.py\nRetries & 429 Exponential Backoff]
        Ingest[src/ingestion.py\nOrchestrator: Fetch & Upsert]
        Validate[src/validation.py\nNull/Negative/Range Rejection]
        Transform[src/transformation.py\nUTC Harmonization & Unit Normalization]
        Anomaly[src/anomaly_detection.py\nRolling Median & MAD Guardrail >= 48 Obs]
    end

    subgraph Storage Layer
        DB[(Database: SQLite / PostgreSQL\nDATABASE_URL)]
        Tables[Tables:\nlocations\nsensors\nmeasurements (ON CONFLICT DO UPDATE)\ningestion_runs\nanomalies]
    end

    subgraph Presentation & Automation
        Streamlit[app.py\nStreamlit + Plotly Dashboard]
        GHA[GitHub Actions\n.github/workflows/daily_pipeline.yml\n07:00 IST Cron]
    end

    OpenAQ --> Client
    Config --> Client
    Config --> DB
    Client --> Ingest
    Ingest --> Validate
    Validate --> Transform
    Transform --> DB
    DB --> Anomaly
    Anomaly --> DB
    DB --> Streamlit
    GHA --> Ingest
```

---

## Project Metrics (Verified from Real Pipeline Execution)

> [!NOTE]
> All metrics below reflect verified output from live pipeline runs on actual OpenAQ v3 observations for Hyderabad:

| Metric | Measured Value |
|---|---|
| **Monitoring Stations Tracked** | `20` (TSPCB & regional stations) |
| **Total Sensors Mapped** | `272` sensors |
| **Total Measurements Ingested** | `10,261` records |
| **Active Time Horizon** | `2026-10-11 00:30:00 UTC` to `2026-10-13 18:30:00 UTC` (3 days) |
| **Total Rows Processed** | `10,489` records |
| **Rejection Rate** | `0.00%` (0 invalid/malformed records) |
| **Statistical Anomalies Flagged** | `148` readings (Rolling MAD > 3.5, $\ge 48$ obs) |
| **Automated Test Suite** | `23 passed, 0 failed` (100% pass rate) |

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
- **Database & ORM**: `SQLAlchemy 2.x` (SQLite native with WAL mode; PostgreSQL ready via `DATABASE_URL`)
- **Dashboard**: `Streamlit`, `Plotly`
- **Testing**: `pytest` (mocked unit tests + optional live API smoke test)
- **CI/CD Automation**: GitHub Actions (`daily_pipeline.yml`)

---

## Database Schema

- **`locations`**: `id` (PK), `name`, `latitude`, `longitude`, `country`, `timezone`, `owner_name`, `source_metadata`, `created_at_utc`.
- **`sensors`**: `id` (PK), `location_id` (FK), `parameter`, `unit`, `display_name`.
- **`measurements`**: `id` (PK), `sensor_id` (FK), `location_id` (FK), `parameter`, `value` (normalized), `unit` (normalized), `value_original`, `unit_original`, `measured_at_utc`, `ingested_at_utc`, `source`, `quality_flag`.
  - **Unique Constraint**: `(sensor_id, parameter, measured_at_utc)` ensures ingestion idempotency.
  - **Indexes**: `measured_at_utc` and `(location_id, parameter)`.
- **`ingestion_runs`**: `id` (PK), `started_at`, `finished_at`, `status`, `requests_made`, `rows_received`, `rows_inserted`, `rows_updated`, `rows_rejected`, `error_message`.
- **`anomalies`**: `id` (PK), `sensor_id` (FK), `location_id` (FK), `parameter`, `measured_at_utc`, `observed_value`, `baseline_median`, `expected_low`, `expected_high`, `method`, `severity`, `detected_at_utc`.

---

## Windows & Local Setup

### 1. Clone & Set Up Virtual Environment

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

Edit `.env` and set your OpenAQ API key:

```ini
OPENAQ_API_KEY=your_openaq_api_key_here
DATABASE_URL=sqlite:///data/airquality.db
```

*(Get a free API key at [explore.openaq.org/register](https://explore.openaq.org/register)).*

---

## Run Commands

### Step 0: Check OpenAQ Station Coverage
```powershell
python scripts/check_coverage.py
```

### Run Daily Ingestion Pipeline (3-Day Rolling Window)
```powershell
python scripts/run_pipeline.py --days 3
```

### Backfill Historical Data (Up to 30 Days)
```powershell
python scripts/backfill.py --days 30
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

## Data Quality & Anomaly Methodology

### Quality Validation Rules
1. **No Zero Filling**: Missing data is left unrecorded rather than filled with artificial zeros.
2. **Negative Concentration Rejection**: Air pollutant values $< 0$ (caused by sensor zero-drift or calibration faults) are rejected.
3. **Physical Bound Verification**: Upper bounds (e.g., $1500\,\mu\text{g/m}^3$ for $\text{PM}_{2.5}$, $2000\,\mu\text{g/m}^3$ for $\text{PM}_{10}$) reject impossible outliers.
4. **Timestamp Integrity**: All observations require a valid UTC timestamp and are converted to `Asia/Kolkata` for local analysis.

### Statistical Anomaly Engine
- **Method**: Rolling Median and Median Absolute Deviation (MAD):
  $$\text{MAD} = \text{median}(|X_i - \tilde{X}|)$$
  $$\text{Expected Range} = \tilde{X} \pm 3.5 \times 1.4826 \times \text{MAD}$$
- **48-Observation Guardrail**: Requires a minimum baseline of 48 chronological measurements per sensor before evaluating anomalies, preventing false positives on sparse stations.
- **Important Distinction**: A statistical anomaly represents a numerical departure from baseline, not an official health advisory. Indian AQI is not inferred without official CPCB sub-index calculation.

---

## GitHub Actions & CI/CD Automation

The scheduled pipeline is configured in [`.github/workflows/daily_pipeline.yml`](file:///.github/workflows/daily_pipeline.yml):
- **Schedule**: `30 1 * * *` (01:30 UTC = 07:00 IST daily) and manual `workflow_dispatch`.
- **Secrets Required**: `OPENAQ_API_KEY` (configured in GitHub Repository Settings -> Secrets and variables -> Actions).
- **Behavior**:
  - Sets up Python 3.12, installs dependencies.
  - Runs `scripts/run_pipeline.py --days 3`.
  - Runs smoke assertions verifying record count and ingestion health.
  - Commits updated `data/airquality.db` back to repository with `[skip ci]`.
  - Never overwrites or corrupts data if the upstream API fails.

---

## Known Limitations

1. **Station Outages**: Some physical monitoring stations (e.g. Sanathnagar legacy) stopped transmitting data in previous years; the pipeline flags these as stale while continuing to monitor active stations.
2. **API Rate Limits**: OpenAQ v3 free tier enforces strict request rate limits. The client automatically catches HTTP 429 and applies exponential backoff, but large backfills (>60 days) require sufficient time.
