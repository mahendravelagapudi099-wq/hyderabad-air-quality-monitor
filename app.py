"""Streamlit Interactive Dashboard for Hyderabad Air Quality Monitor."""

from datetime import datetime, timezone
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analytics import (
    get_anomalies_df,
    get_available_parameters,
    get_ingestion_history_df,
    get_locations_list,
    get_measurement_timeseries,
    get_overview_metrics,
)
from src.database import get_session, init_db

# Page Setup
st.set_page_config(
    page_title="Hyderabad Air Quality Monitor",
    page_icon="🍃",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Dark Glassmorphism & Modern Typography)
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }

    .main {
        background-color: #0b0f19;
    }

    .metric-card {
        background: linear-gradient(135deg, rgba(22, 27, 34, 0.75), rgba(15, 23, 42, 0.85));
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 22px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(12px);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }

    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.4);
    }

    .metric-title {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .metric-value {
        color: #f8fafc;
        font-size: 2.1rem;
        font-weight: 800;
        margin: 6px 0;
    }

    .metric-sub {
        color: #38bdf8;
        font-size: 0.85rem;
        font-weight: 500;
    }

    .pill-active {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        background: rgba(34, 197, 94, 0.15);
        color: #4ade80;
        font-size: 0.8rem;
        font-weight: 700;
        border: 1px solid rgba(34, 197, 94, 0.3);
    }

    .pill-warning {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        background: rgba(234, 179, 8, 0.15);
        color: #facc15;
        font-size: 0.8rem;
        font-weight: 700;
        border: 1px solid rgba(234, 179, 8, 0.3);
    }

    .hero-title {
        background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.6rem;
        margin-bottom: 0.2rem;
    }

    .hero-sub {
        color: #94a3b8;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize DB if not present
init_db()


def main():
    st.markdown('<div class="hero-title">Hyderabad Air Quality Monitor</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-sub">Autonomous Data-Engineering Pipeline Tracking Real OpenAQ v3 Observations across Telangana</div>',
        unsafe_allow_html=True,
    )

    with get_session() as session:
        metrics = get_overview_metrics(session)
        locations = get_locations_list(session)
        all_params = get_available_parameters(session)

    # Sidebar Filter Controls
    st.sidebar.header("Navigation & Filters")
    time_filter = st.sidebar.selectbox(
        "Time Window",
        options=["Last 24 Hours", "Last 3 Days", "Last 7 Days", "Last 30 Days", "All History"],
        index=2,
    )
    days_map = {
        "Last 24 Hours": 1,
        "Last 3 Days": 3,
        "Last 7 Days": 7,
        "Last 30 Days": 30,
        "All History": 0,
    }
    selected_days = days_map[time_filter]

    loc_options = {loc["name"]: loc["id"] for loc in locations}
    selected_loc_names = st.sidebar.multiselect(
        "Filter Stations",
        options=list(loc_options.keys()),
        default=list(loc_options.keys())[:4] if len(loc_options) >= 4 else list(loc_options.keys()),
    )
    selected_loc_ids = [loc_options[name] for name in selected_loc_names]

    # Overview KPI Metrics Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Active Stations</div>
                <div class="metric-value">{metrics["station_count"]}</div>
                <div class="metric-sub">{metrics["sensor_count"]} total sensors mapped</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Total Records</div>
                <div class="metric-value">{metrics["total_records"]:,}</div>
                <div class="metric-sub">Deduplicated measurements</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        fresh_class = "pill-active" if "Live" in metrics["freshness_status"] or "Recent" in metrics["freshness_status"] else "pill-warning"
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Data Freshness</div>
                <div class="metric-value"><span class="{fresh_class}">{metrics["freshness_status"]}</span></div>
                <div class="metric-sub">Last sync: {metrics["last_run_status"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-title">Detected Anomalies</div>
                <div class="metric-value">{metrics["total_anomalies"]}</div>
                <div class="metric-sub">Rolling MAD &gt; 3.5 (&ge; 48 obs)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    # If empty database
    if metrics["total_records"] == 0:
        st.info(
            "Database is currently empty. Run `python scripts/run_pipeline.py` or "
            "`python scripts/backfill.py` to ingest real OpenAQ v3 observations for Hyderabad."
        )
        return

    # Tabs
    tab_trends, tab_stations, tab_anomalies, tab_health = st.tabs([
        "📈 Pollutant Trends",
        "📍 Station Comparisons",
        "⚠️ Statistical Anomalies",
        "🏥 Pipeline Health",
    ])

    # 1. Trends Tab
    with tab_trends:
        st.subheader("Particulate Matter (PM2.5 & PM10)")
        with get_session() as session:
            df_pm = get_measurement_timeseries(
                session=session,
                parameters=["pm25", "pm10"],
                location_ids=selected_loc_ids or None,
                days=selected_days,
            )

        if not df_pm.empty:
            fig_pm = px.line(
                df_pm,
                x="measured_at_ist",
                y="value",
                color="parameter",
                line_dash="location_name",
                labels={"value": "Concentration (µg/m³)", "measured_at_ist": "Local Time (IST)", "parameter": "Pollutant", "location_name": "Station"},
                template="plotly_dark",
            )
            fig_pm.update_layout(
                plot_bgcolor="rgba(15, 23, 42, 0.4)",
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=450,
            )
            st.plotly_chart(fig_pm, use_container_width=True)
        else:
            st.warning("No PM2.5 / PM10 records found for selected filter criteria.")

        st.subheader("Gaseous Pollutants (NO2, SO2, CO, O3)")
        st.caption("Note: Gaseous units are plotted separately (µg/m³ vs. ppb) to avoid mixing scales.")

        with get_session() as session:
            df_gas = get_measurement_timeseries(
                session=session,
                parameters=["no2", "so2", "co", "o3"],
                location_ids=selected_loc_ids or None,
                days=selected_days,
            )

        if not df_gas.empty:
            units_present = df_gas["unit"].unique()
            for u in units_present:
                sub_df = df_gas[df_gas["unit"] == u]
                fig_gas = px.line(
                    sub_df,
                    x="measured_at_ist",
                    y="value",
                    color="parameter",
                    line_dash="location_name",
                    title=f"Pollutants in {u}",
                    labels={"value": f"Concentration ({u})", "measured_at_ist": "Local Time (IST)"},
                    template="plotly_dark",
                )
                fig_gas.update_layout(
                    plot_bgcolor="rgba(15, 23, 42, 0.4)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    height=380,
                )
                st.plotly_chart(fig_gas, use_container_width=True)
        else:
            st.info("No gaseous pollutant observations found for this time range.")

    # 2. Station Comparisons Tab
    with tab_stations:
        st.subheader("Station Comparison & Daily Averages")
        with get_session() as session:
            df_comp = get_measurement_timeseries(
                session=session,
                parameters=["pm25", "pm10", "no2"],
                days=selected_days,
            )

        if not df_comp.empty:
            # Average concentration by station
            avg_df = (
                df_comp.groupby(["location_name", "parameter"])["value"]
                .mean()
                .reset_index()
            )
            fig_bar = px.bar(
                avg_df,
                x="location_name",
                y="value",
                color="parameter",
                barmode="group",
                labels={"value": "Mean Concentration (µg/m³)", "location_name": "Station", "parameter": "Pollutant"},
                title="Average Pollutant Levels Across Hyderabad Monitoring Stations",
                template="plotly_dark",
            )
            fig_bar.update_layout(
                plot_bgcolor="rgba(15, 23, 42, 0.4)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=450,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

            # Station Locations Table
            st.subheader("Hyderabad Monitoring Network Stations")
            loc_df = pd.DataFrame(locations)[["name", "latitude", "longitude", "timezone"]]
            st.dataframe(loc_df, use_container_width=True)
        else:
            st.info("No comparison data available.")

    # 3. Anomalies Tab
    with tab_anomalies:
        st.subheader("Flagged Statistical Anomalies")
        st.caption(
            "Anomalies are detected using rolling Median and Median Absolute Deviation (MAD > 3.5) "
            "with a strict guardrail requiring at least 48 observations before flagging. "
            "A statistical anomaly indicates a mathematical outlier, not necessarily a health warning."
        )

        with get_session() as session:
            df_anom = get_anomalies_df(session, limit=150)

        if not df_anom.empty:
            # Formatting for display
            display_cols = [
                "measured_at_ist",
                "location_name",
                "parameter",
                "observed_value",
                "baseline_median",
                "expected_low",
                "expected_high",
                "severity",
                "method",
            ]
            st.dataframe(
                df_anom[display_cols].rename(
                    columns={
                        "measured_at_ist": "Time (IST)",
                        "location_name": "Station",
                        "parameter": "Pollutant",
                        "observed_value": "Observed",
                        "baseline_median": "Median Baseline",
                        "expected_low": "Expected Min",
                        "expected_high": "Expected Max",
                        "severity": "Severity",
                        "method": "Detection Method",
                    }
                ),
                use_container_width=True,
            )
        else:
            st.success("No statistical anomalies detected in the current observation window.")

    # 4. Pipeline Health Tab
    with tab_health:
        st.subheader("Ingestion Run Audit & Data Quality Logs")
        with get_session() as session:
            df_history = get_ingestion_history_df(session, limit=30)

        if not df_history.empty:
            st.dataframe(df_history, use_container_width=True)

            # Summary chart of rows inserted vs rejected
            fig_health = go.Figure()
            fig_health.add_trace(
                go.Bar(
                    x=df_history["Run ID"],
                    y=df_history["Inserted"],
                    name="Rows Ingested/Updated",
                    marker_color="#38bdf8",
                )
            )
            fig_health.add_trace(
                go.Bar(
                    x=df_history["Run ID"],
                    y=df_history["Rejected"],
                    name="Rows Rejected (Invalid/Null)",
                    marker_color="#f43f5e",
                )
            )
            fig_health.update_layout(
                barmode="stack",
                title="Ingestion Throughput vs Data Quality Rejections",
                xaxis_title="Run ID",
                yaxis_title="Record Count",
                template="plotly_dark",
                plot_bgcolor="rgba(15, 23, 42, 0.4)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=380,
            )
            st.plotly_chart(fig_health, use_container_width=True)
        else:
            st.info("No ingestion audit runs logged yet.")


if __name__ == "__main__":
    main()
