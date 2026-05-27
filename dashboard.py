"""
dashboard.py – Real-time Foster Care Placement Monitor (Streamlit + Plotly).

Run with:
    streamlit run dashboard.py

Connects to the Artifex API WebSocket for live placement data and
polls /agent/status for agent health.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(
    page_title="Foster Care Swarm Dashboard",
    page_icon="🚸",
    layout="wide",
)

st.title("🚸 Foster Care Swarm – Real-Time Monitoring")
st.caption("Live placement tracking · Risk scoring · Agent health · Powered by Artifex")

WS_URL   = "ws://localhost:8000/ws/dashboard"
REST_URL = "http://localhost:8000"

# ── Shared state (thread-safe) ────────────────────────────────────────────────
_state: dict[str, Any] = {
    "placements":  [],
    "alerts":      [],   # deduplicated high-risk alerts
    "last_update": None,
    "error":       None,
    "connected":   False,
}
_lock = threading.Lock()


def _ws_listener() -> None:
    """Background thread: connect to WebSocket and keep shared state current."""
    import websocket  # websocket-client

    def on_message(ws, message: str) -> None:
        data = json.loads(message)
        placements = data.get("placements", [])
        now = datetime.now()
        with _lock:
            _state["placements"]  = placements
            _state["last_update"] = now.strftime("%H:%M:%S")
            _state["error"]       = None
            _state["connected"]   = True
            # Deduplicated alert log
            seen = {a["child_id"] for a in _state["alerts"]}
            for p in placements:
                if p.get("risk_score", 0) > 75 and p.get("child_id") not in seen:
                    _state["alerts"].append({
                        "child_id":  p["child_id"],
                        "risk":      p["risk_score"],
                        "timestamp": now.strftime("%H:%M:%S"),
                        "notes":     p.get("last_notes", "")[:80],
                        "family":    p.get("family", {}).get("name", "?"),
                    })
                    seen.add(p["child_id"])
            _state["alerts"] = _state["alerts"][-20:]   # keep last 20

    def on_error(ws, error: Exception) -> None:
        with _lock:
            _state["error"]     = str(error)
            _state["connected"] = False

    def on_close(ws, *_) -> None:
        with _lock:
            _state["connected"] = False
            _state["error"]     = "WebSocket closed – reconnecting..."
        time.sleep(3)
        _ws_listener()   # reconnect

    ws = websocket.WebSocketApp(
        WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()


# Start background listener once per session
if "ws_started" not in st.session_state:
    st.session_state["ws_started"] = True
    threading.Thread(target=_ws_listener, daemon=True).start()
    time.sleep(1)   # give the thread a moment to connect


# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")
    auto_refresh = st.toggle("Auto-refresh (3 s)", value=True)
    risk_threshold = st.slider("High-risk threshold (%)", 50, 95, 75)
    st.divider()
    st.header("🤖 Agent Health")
    agents = ["planner", "retriever", "executor", "validator",
              "supervisor", "foster_monitor"]
    for agent in agents:
        try:
            r = requests.get(f"{REST_URL}/agent/status/{agent}", timeout=1)
            info = r.json()
            status = info.get("status", "unknown")
            age    = info.get("last_heartbeat_age_s")
            icon   = "🟢" if status == "healthy" else ("🟡" if status == "unknown" else "🔴")
            label  = f"{icon} {agent}"
            detail = f"{age:.0f}s ago" if age is not None else "no heartbeat"
            st.metric(label, detail)
        except Exception:
            st.metric(f"🔴 {agent}", "unreachable")


# ── Main content ──────────────────────────────────────────────────────────────
with _lock:
    placements  = list(_state["placements"])
    alerts      = list(_state["alerts"])
    last_update = _state["last_update"]
    error       = _state["error"]
    connected   = _state["connected"]

# Connection status bar
status_col, refresh_col = st.columns([4, 1])
with status_col:
    if connected:
        st.success(f"🟢 Connected · Last update: {last_update}")
    elif error:
        st.error(f"🔴 {error}")
    else:
        st.info("⏳ Connecting to WebSocket...")
with refresh_col:
    if st.button("🔄 Refresh Now"):
        st.rerun()

st.divider()

if not placements:
    st.info("No active placements yet. Run the simulation to generate data:")
    st.code("python scripts/simulate_foster_events_from_json.py --count 5 --delay 2 --checkins 2")
else:
    # ── Summary metrics ───────────────────────────────────────────────────────
    total      = len(placements)
    high_risk  = sum(1 for p in placements if p.get("risk_score", 0) > risk_threshold)
    med_risk   = sum(1 for p in placements if 40 < p.get("risk_score", 0) <= risk_threshold)
    low_risk   = total - high_risk - med_risk
    avg_risk   = sum(p.get("risk_score", 0) for p in placements) / total

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Placements", total)
    m2.metric(f"🔴 High Risk (>{risk_threshold}%)", high_risk)
    m3.metric("🟡 Medium Risk", med_risk)
    m4.metric("🟢 Low Risk", low_risk)
    m5.metric("📊 Avg Risk", f"{avg_risk:.1f}%")

    st.divider()

    # ── Charts row ────────────────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    df = pd.DataFrame(placements)
    df["risk_score"] = pd.to_numeric(df.get("risk_score", 0), errors="coerce").fillna(0)
    df["child_id"]   = df.get("child_id", "unknown")
    df["family_name"] = df["family"].apply(
        lambda f: f.get("name", f.get("family_id", "?")) if isinstance(f, dict) else "?"
    )

    with chart_col1:
        st.subheader("📊 Risk Score Distribution")
        fig_hist = px.histogram(
            df, x="risk_score", nbins=20,
            color_discrete_sequence=["#e74c3c"],
            labels={"risk_score": "Risk Score (%)"},
        )
        fig_hist.add_vline(x=risk_threshold, line_dash="dash",
                           line_color="orange", annotation_text="Threshold")
        fig_hist.update_layout(margin=dict(t=20, b=20), height=300)
        st.plotly_chart(fig_hist, use_container_width=True)

    with chart_col2:
        st.subheader("🏠 Risk by Family")
        fig_bar = px.bar(
            df.sort_values("risk_score", ascending=False).head(15),
            x="child_id", y="risk_score", color="family_name",
            labels={"risk_score": "Risk %", "child_id": "Child"},
        )
        fig_bar.add_hline(y=risk_threshold, line_dash="dash", line_color="red")
        fig_bar.update_layout(margin=dict(t=20, b=20), height=300,
                              showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Risk trend (from risk_history embedded in placements) ─────────────────
    st.subheader("📈 Risk Trend (from check-in history)")
    trend_rows = []
    for p in placements:
        for i, h in enumerate(p.get("risk_history", [])):
            trend_rows.append({
                "child_id":  p.get("child_id", "?"),
                "check_in":  i + 1,
                "risk_score": h.get("score", 0),
                "notes":     h.get("notes", "")[:40],
            })
    if trend_rows:
        trend_df = pd.DataFrame(trend_rows)
        fig_line = px.line(
            trend_df, x="check_in", y="risk_score", color="child_id",
            markers=True,
            labels={"check_in": "Check-in #", "risk_score": "Risk %"},
        )
        fig_line.add_hline(y=risk_threshold, line_dash="dash",
                           line_color="red", annotation_text="Alert threshold")
        fig_line.update_layout(height=350)
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("Risk trend appears after check-ins are processed.")

    st.divider()

    # ── Placement cards ───────────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📋 Active Placements")
        for p in sorted(placements, key=lambda x: x.get("risk_score", 0), reverse=True):
            risk   = p.get("risk_score", 0)
            child  = p.get("child_id", "?")
            family = p.get("family", {})
            fname  = family.get("name", family.get("family_id", "?")) if isinstance(family, dict) else "?"
            notes  = p.get("last_notes", "")
            expl   = p.get("risk_explanation", "")
            icon   = "🔴" if risk > risk_threshold else ("🟡" if risk > 40 else "🟢")

            with st.expander(f"{icon} {child} → {fname}  |  Risk: {risk:.0f}%"):
                c1, c2 = st.columns(2)
                c1.write(f"**Family:** {fname}")
                c1.write(f"**Location:** {family.get('location', 'N/A') if isinstance(family, dict) else 'N/A'}")
                c1.write(f"**Workflow:** `{p.get('workflow_id', '')}`")
                c2.metric("Disruption Risk", f"{risk:.0f}%")
                if notes:
                    st.write(f"**Latest notes:** {notes}")
                if expl:
                    st.caption(f"📐 {expl}")
                if risk > risk_threshold:
                    st.error("⚠️ Immediate caseworker review required")

    with col_right:
        st.subheader(f"⚠️ High-Risk Alerts (>{risk_threshold}%)")
        if alerts:
            alert_df = pd.DataFrame(alerts[::-1])   # newest first
            st.dataframe(
                alert_df[["timestamp", "child_id", "risk", "family", "notes"]],
                use_container_width=True,
                hide_index=True,
            )
            # Gauge for highest current risk
            max_risk = max(p.get("risk_score", 0) for p in placements)
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=max_risk,
                title={"text": "Highest Active Risk"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar":  {"color": "#e74c3c"},
                    "steps": [
                        {"range": [0, 40],  "color": "#2ecc71"},
                        {"range": [40, 75], "color": "#f39c12"},
                        {"range": [75, 100],"color": "#e74c3c"},
                    ],
                    "threshold": {
                        "line": {"color": "black", "width": 4},
                        "thickness": 0.75,
                        "value": risk_threshold,
                    },
                },
            ))
            fig_gauge.update_layout(height=280, margin=dict(t=30, b=10))
            st.plotly_chart(fig_gauge, use_container_width=True)
        else:
            st.success(f"✅ No active alerts above {risk_threshold}%")

st.caption("Data updates every 2 seconds via WebSocket · Risk model uses cumulative decay")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(3)
    st.rerun()
