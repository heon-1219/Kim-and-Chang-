"""
Bot Log Analytics — full log viewer page.
Reached via st.switch_page() from the main dashboard.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db

db.init_db()

st.set_page_config(
    page_title="Bot Logs — KC Trading",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Auth guard ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated"):
    st.switch_page("dashboard.py")
    st.stop()

DEMO = st.session_state.get("demo", False)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
header[data-testid="stHeader"] { display:none !important; }
[data-testid="stToolbar"]       { display:none !important; }
[data-testid="stSidebarCollapsedControl"] { display:none; }
.block-container { max-width:100% !important; padding:0.3rem 0.8rem 0.6rem !important; }
hr { border-color:#1e3a5f !important; margin:0.3rem 0 !important; }
[data-testid="stMetricLabel"] > div { font-size:0.55rem !important; text-transform:uppercase; letter-spacing:0.07em; }
[data-testid="stMetricValue"]       { font-size:0.95rem !important; }
</style>""", unsafe_allow_html=True)

_CHART = dict(
    paper_bgcolor="#0a0e1a", plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(l=0, r=8, t=24, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
)
_NO_TB = {"displayModeBar": False}

_LEVEL_STYLE = {
    "ERROR": "color:#ff4b4b;font-weight:600",
    "WARN":  "color:#ffa500",
    "INFO":  "color:#6b8bb0",
}
_SIDE_STYLE = {
    "buy":  "color:#00c896;font-weight:600",
    "sell": "color:#ff4b4b;font-weight:600",
}

# ── Demo data ─────────────────────────────────────────────────────────────────
def _demo_logs():
    return [
        {"id":1,"timestamp":"2026-04-18 09:00","level":"INFO", "message":"Bot cycle started"},
        {"id":2,"timestamp":"2026-04-18 08:55","level":"INFO", "message":"rsi/AAPL: $178.91 → hold"},
        {"id":3,"timestamp":"2026-04-18 08:54","level":"INFO", "message":"rsi/GOOGL: $169.55 → buy"},
        {"id":4,"timestamp":"2026-04-18 08:50","level":"WARN", "message":"API rate limit approaching: 178/200"},
        {"id":5,"timestamp":"2026-04-17 15:30","level":"ERROR","message":"Order rejected: insufficient buying power"},
        {"id":6,"timestamp":"2026-04-17 14:32","level":"INFO", "message":"[RSI] BUY 10 AAPL @ $171.42 (sim $171.51)"},
        {"id":7,"timestamp":"2026-04-17 10:11","level":"INFO", "message":"[MACD] BUY 5 MSFT @ $415.80 (sim $415.87)"},
        {"id":8,"timestamp":"2026-04-16 15:47","level":"INFO", "message":"[RSI] SELL 8 GOOGL @ $169.55 (sim $169.47)"},
        {"id":9,"timestamp":"2026-04-16 09:35","level":"INFO", "message":"macd/MSFT: $415.80 → buy"},
        {"id":10,"timestamp":"2026-04-15 11:22","level":"WARN", "message":"Market closed. Next open: 2026-04-16 09:30"},
    ]

def _demo_trades():
    return [
        {"id":1,"timestamp":"2026-04-17 14:32","symbol":"AAPL", "side":"buy", "quantity":10,"actual_price":171.42,"strategy":"rsi",    "notes":"signal: buy"},
        {"id":2,"timestamp":"2026-04-17 10:11","symbol":"MSFT", "side":"buy", "quantity":5, "actual_price":415.80,"strategy":"macd",   "notes":"signal: buy"},
        {"id":3,"timestamp":"2026-04-16 15:47","symbol":"GOOGL","side":"sell","quantity":8, "actual_price":169.55,"strategy":"rsi",    "notes":"signal: sell"},
        {"id":4,"timestamp":"2026-04-14 09:35","symbol":"TSLA", "side":"buy", "quantity":3, "actual_price":242.10,"strategy":"bollinger","notes":"signal: buy"},
        {"id":5,"timestamp":"2026-04-13 11:22","symbol":"TSLA", "side":"sell","quantity":3, "actual_price":251.80,"strategy":"bollinger","notes":"signal: sell"},
    ]

# ── Load data ─────────────────────────────────────────────────────────────────
log_day = st.date_input("Log date (UTC)", value=date.today())
log_start = datetime.combine(log_day, datetime.min.time())
log_end = log_start + timedelta(days=1)
raw_logs   = _demo_logs()   if DEMO else db.get_logs_for_window(log_start, log_end, limit=5000)
raw_trades = _demo_trades() if DEMO else db.get_recent_trades(limit=500)

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([8, 2])
with h1:
    st.markdown(
        '<span style="font-size:0.6rem;letter-spacing:0.2em;color:#00d4aa;">KC TRADING TECHNOLOGIES</span><br>'
        '<span style="font-size:1.15rem;font-weight:700;">Bot Log Analytics</span>',
        unsafe_allow_html=True)
with h2:
    if st.button("← Back to Dashboard", use_container_width=True):
        st.switch_page("dashboard.py")
st.divider()

# ── Summary metrics ───────────────────────────────────────────────────────────
df_logs = pd.DataFrame(raw_logs) if raw_logs else pd.DataFrame(columns=["timestamp","level","message"])
n_info  = int((df_logs["level"] == "INFO").sum())  if not df_logs.empty else 0
n_warn  = int((df_logs["level"] == "WARN").sum())  if not df_logs.empty else 0
n_err   = int((df_logs["level"] == "ERROR").sum()) if not df_logs.empty else 0

df_trades = pd.DataFrame(raw_trades) if raw_trades else pd.DataFrame()
n_buys  = int((df_trades["side"] == "buy").sum())  if not df_trades.empty and "side" in df_trades.columns else 0
n_sells = int((df_trades["side"] == "sell").sum()) if not df_trades.empty and "side" in df_trades.columns else 0

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total Log Entries", f"{len(df_logs):,}")
m2.metric("INFO",  str(n_info),  delta=None)
m3.metric("WARN",  str(n_warn),  delta=None)
m4.metric("ERROR", str(n_err),   delta=None)
m5.metric("Buys",  str(n_buys))
m6.metric("Sells", str(n_sells))
st.divider()

# ── Log Viewer ────────────────────────────────────────────────────────────────
lv_left, lv_right = st.columns([3, 1])

with lv_left:
    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                'text-transform:uppercase;letter-spacing:0.1em;">Log Entries</p>',
                unsafe_allow_html=True)

    # Filters
    fc1, fc2 = st.columns([1, 3])
    with fc1:
        level_filter = st.multiselect(
            "Level", ["INFO","WARN","ERROR"],
            default=["INFO","WARN","ERROR"],
            label_visibility="collapsed")
    with fc2:
        search_text = st.text_input("Search messages…", placeholder="Search messages…",
                                    label_visibility="collapsed")

    filtered = df_logs.copy()
    if level_filter:
        filtered = filtered[filtered["level"].isin(level_filter)]
    if search_text:
        mask = filtered["message"].str.contains(search_text, case=False, na=False)
        filtered = filtered[mask]

    if not filtered.empty:
        cols_show = [c for c in ["timestamp","level","message"] if c in filtered.columns]
        styled_log = (
            filtered[cols_show]
            .style
            .map(lambda v: _LEVEL_STYLE.get(v, ""), subset=["level"])
        )
        st.dataframe(styled_log, use_container_width=True, hide_index=True, height=460)
        st.caption(f"Showing {len(filtered):,} of {len(df_logs):,} entries")
    else:
        st.caption("No log entries match the current filters.")

with lv_right:
    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                'text-transform:uppercase;letter-spacing:0.1em;">Log Level Distribution</p>',
                unsafe_allow_html=True)
    if not df_logs.empty:
        level_counts = df_logs["level"].value_counts()
        fig_lv = go.Figure(go.Pie(
            labels=level_counts.index.tolist(),
            values=level_counts.values.tolist(),
            hole=0.45,
            marker=dict(colors=["#6b8bb0","#ffa500","#ff4b4b"]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>%{value} entries (%{percent})<extra></extra>"))
        fig_lv.update_layout(
            paper_bgcolor="#0a0e1a", font=dict(color="#e2e8f0", size=10),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=0, r=0, t=10, b=0), height=200)
        st.plotly_chart(fig_lv, use_container_width=True, config=_NO_TB)

    # Signal events — log lines containing "→" (strategy signals)
    st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                'text-transform:uppercase;letter-spacing:0.1em;margin-top:12px;">'
                'Signal Events</p>', unsafe_allow_html=True)
    if not df_logs.empty:
        sig_df = df_logs[df_logs["message"].str.contains("→", na=False)].copy()
        if not sig_df.empty:
            # Parse: "rsi/AAPL: $171.42 → buy"
            sig_df["signal"] = sig_df["message"].str.extract(r"→\s*(\w+)$")
            sig_df["sym_col"] = sig_df["message"].str.extract(r"/(\w+):")
            cols_s = [c for c in ["timestamp","sym_col","signal"] if c in sig_df.columns]
            sig_df_show = sig_df[cols_s].rename(columns={"sym_col":"Symbol","signal":"Signal"})
            _SIG_STYLE = {"buy":"color:#00c896;font-weight:600","sell":"color:#ff4b4b;font-weight:600"}
            sig_styled = sig_df_show.style.map(lambda v: _SIG_STYLE.get(str(v).lower(),""),
                                                subset=["Signal"])
            st.dataframe(sig_styled, use_container_width=True, hide_index=True, height=200)
        else:
            st.caption("No signal events found in logs.")
    else:
        st.caption("No log data.")

st.divider()

# ── Trade Analytics ───────────────────────────────────────────────────────────
st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
            'text-transform:uppercase;letter-spacing:0.1em;">Trade Analytics</p>',
            unsafe_allow_html=True)

if not df_trades.empty and "strategy" in df_trades.columns:
    ta1, ta2, ta3 = st.columns([2, 2, 3])

    with ta1:
        st.markdown("**Trades by Strategy**")
        strat_counts = df_trades["strategy"].value_counts()
        fig_strat = go.Figure(go.Bar(
            x=strat_counts.index.tolist(), y=strat_counts.values.tolist(),
            marker_color=["#4ecdc4","#f7b731","#a29bfe","#fd9644","#74b9ff"],
            hovertemplate="<b>%{x}</b><br>%{y} trades<extra></extra>"))
        fig_strat.update_layout(**_CHART, height=200, showlegend=False)
        st.plotly_chart(fig_strat, use_container_width=True, config=_NO_TB)

    with ta2:
        st.markdown("**Trades by Symbol**")
        if "symbol" in df_trades.columns:
            sym_counts = df_trades.groupby(["symbol","side"]).size().unstack(fill_value=0)
            fig_sym = go.Figure()
            if "buy" in sym_counts.columns:
                fig_sym.add_trace(go.Bar(
                    name="Buy", x=sym_counts.index.tolist(),
                    y=sym_counts["buy"].tolist(), marker_color="#00c896"))
            if "sell" in sym_counts.columns:
                fig_sym.add_trace(go.Bar(
                    name="Sell", x=sym_counts.index.tolist(),
                    y=sym_counts["sell"].tolist(), marker_color="#ff4b4b"))
            fig_sym.update_layout(**_CHART, height=200, barmode="group")
            st.plotly_chart(fig_sym, use_container_width=True, config=_NO_TB)

    with ta3:
        st.markdown("**Recent Trades**")
        cols_t = [c for c in
                  ["timestamp","symbol","side","quantity","actual_price","strategy","notes"]
                  if c in df_trades.columns]
        fmt_t: dict = {}
        if "actual_price" in df_trades.columns: fmt_t["actual_price"] = "${:.2f}"
        if "quantity"     in df_trades.columns: fmt_t["quantity"]     = "{:.0f}"
        styled_t = df_trades[cols_t].style.format(fmt_t, na_rep="—")
        if "side" in cols_t:
            styled_t = styled_t.map(lambda v: _SIDE_STYLE.get(v,""), subset=["side"])
        st.dataframe(styled_t, use_container_width=True, hide_index=True, height=200)

    # What triggered each trade
    st.markdown("---")
    st.markdown("**What Triggered Each Trade**")
    st.caption(
        "Each trade row is matched against the nearest preceding signal log entry "
        "(lines containing '→'). Strategy and signal are sourced from the trade log "
        "(strategy column) and bot_log (signal column).")

    if not df_logs.empty:
        sig_events = df_logs[df_logs["message"].str.contains("→", na=False)].copy()
        sig_events["signal"]   = sig_events["message"].str.extract(r"→\s*(\w+)$")
        sig_events["strategy"] = sig_events["message"].str.extract(r"^(\w+)/")
        sig_events["symbol"]   = sig_events["message"].str.extract(r"/(\w+):")
        sig_events["price_log"]= sig_events["message"].str.extract(r"\$([0-9.]+)")

    if not df_trades.empty and not df_logs.empty and not sig_events.empty:
        trigger_rows = []
        for _, tr in df_trades.iterrows():
            sym_match   = sig_events["symbol"] == tr.get("symbol", "")
            side_match  = sig_events["signal"].str.lower() == str(tr.get("side","")).lower()
            match = sig_events[sym_match & side_match]
            nearest_ts = match["timestamp"].iloc[0] if not match.empty else "—"
            trigger_rows.append({
                "Trade Time":     tr.get("timestamp",""),
                "Symbol":         tr.get("symbol",""),
                "Side":           tr.get("side",""),
                "Strategy":       tr.get("strategy",""),
                "Trigger Signal": tr.get("notes",""),
                "Signal Logged":  nearest_ts,
                "Price":          f"${float(tr.get('actual_price',0)):.2f}",
            })
        df_trigger = pd.DataFrame(trigger_rows)
        _SS = {"buy":"color:#00c896;font-weight:600","sell":"color:#ff4b4b;font-weight:600"}
        styled_trig = df_trigger.style.map(lambda v: _SS.get(str(v).lower(),""), subset=["Side"])
        st.dataframe(styled_trig, use_container_width=True, hide_index=True, height=240)
    else:
        st.caption("No trade data to analyze.")
else:
    st.info("No trade history recorded yet.")
