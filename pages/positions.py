"""
Open Positions — full analytics page.
Reached via st.switch_page() from the main dashboard.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import db
from strategies import STRATEGIES

db.init_db()

st.set_page_config(
    page_title="Open Positions — KC Trading",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Auth guard ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated"):
    st.switch_page("dashboard.py")
    st.stop()

DEMO  = st.session_state.get("demo",  False)
GUEST = st.session_state.get("guest", False)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
header[data-testid="stHeader"] { display:none !important; }
[data-testid="stToolbar"]       { display:none !important; }
[data-testid="stSidebarCollapsedControl"] { display:none; }
.block-container { max-width:100% !important; padding:0.3rem 0.8rem 0.6rem !important; }
hr { border-color:#1e3a5f !important; margin:0.3rem 0 !important; }
[data-testid="stMetricLabel"] > div { font-size:0.55rem !important; text-transform:uppercase; letter-spacing:0.07em; }
[data-testid="stMetricValue"]       { font-size:0.95rem !important; }
[data-testid="stMetricDelta"]       { font-size:0.58rem !important; }
</style>""", unsafe_allow_html=True)

_CHART = dict(
    paper_bgcolor="#0a0e1a", plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(l=0, r=8, t=18, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
)
_NO_TB = {"displayModeBar": False}
_STRAT_CLR = {
    "rsi": "#4ecdc4", "macd": "#f7b731",
    "bollinger": "#a29bfe", "ema_crossover": "#fd9644", "manual": "#74b9ff",
}
_PIE_COLORS = ["#00c896","#4ecdc4","#f7b731","#a29bfe","#fd9644","#74b9ff","#ff6b9d","#c7ecee"]


class _SnapPosition:
    """Stand-in for an Alpaca Position — same shape the live SDK returns,
    populated from the bot-written snapshot so this page never calls Alpaca."""
    __slots__ = ("symbol", "qty", "avg_entry_price", "current_price",
                 "market_value", "unrealized_pl", "unrealized_plpc")

    def __init__(self, d: dict) -> None:
        self.symbol           = d.get("symbol", "")
        self.qty              = d.get("qty", "0")
        self.avg_entry_price  = d.get("avg_entry_price", "0")
        self.current_price    = d.get("current_price", "0")
        self.market_value     = d.get("market_value", "0")
        self.unrealized_pl    = d.get("unrealized_pl", "0")
        self.unrealized_plpc  = d.get("unrealized_plpc", "0")


def _cached_all_positions() -> list[_SnapPosition]:
    """Read from the bot-written snapshot. Never calls Alpaca; the bot keeps
    this fresh during healthy trading cycles."""
    raw = db.get_snapshot("positions")
    if not isinstance(raw, list):
        return []
    return [_SnapPosition(p) for p in raw]

def _num_style(v) -> str:
    try:
        n = float(str(v).replace("$","").replace(",","").replace("%","").replace("+",""))
        if n > 0: return "color:#00c896"
        if n < 0: return "color:#ff4b4b"
    except (ValueError, TypeError):
        pass
    return ""

# ── Demo helpers ──────────────────────────────────────────────────────────────
def _demo_positions():
    class _P:
        def __init__(self, sym, qty, entry, cur, val, pl, plpc, strat):
            self.symbol=sym; self.qty=str(qty); self.avg_entry_price=str(entry)
            self.current_price=str(cur); self.market_value=str(val)
            self.unrealized_pl=str(pl); self.unrealized_plpc=str(plpc/100)
            self._strat=strat
    return [
        _P("AAPL", 10, 171.42, 178.91, 1789.10,  74.90,  4.37, "rsi"),
        _P("MSFT",  5, 415.80, 421.33, 2106.65,  27.65,  1.33, "macd"),
        _P("GOOGL", 8, 172.18, 169.55, 1356.40, -20.40, -1.48, "rsi"),
        _P("TSLA",  2, 248.50, 242.10,  484.20, -12.80, -2.58, "manual"),
    ]

_DEMO_STRAT_POS: dict[str, list[dict]] = {
    "rsi":          [{"Symbol":"AAPL","Qty":10,"Avg Entry":171.42,"Price":178.91,"Mkt Value":1789.10,"P&L ($)": 74.90,"P&L (%)": 4.37},
                     {"Symbol":"GOOGL","Qty":8,"Avg Entry":172.18,"Price":169.55,"Mkt Value":1356.40,"P&L ($)":-20.40,"P&L (%)":-1.48}],
    "macd":         [{"Symbol":"MSFT","Qty":5,"Avg Entry":415.80,"Price":421.33,"Mkt Value":2106.65,"P&L ($)": 27.65,"P&L (%)": 1.33}],
    "bollinger":    [],
    "ema_crossover":[],
    "manual":       [{"Symbol":"TSLA","Qty":2,"Avg Entry":248.50,"Price":242.10,"Mkt Value": 484.20,"P&L ($)":-12.80,"P&L (%)":-2.58}],
}

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([8, 2])
with h1:
    st.markdown(
        '<span style="font-size:0.6rem;letter-spacing:0.2em;color:#00d4aa;">KC TRADING TECHNOLOGIES</span><br>'
        '<span style="font-size:1.15rem;font-weight:700;">Open Positions Analytics</span>',
        unsafe_allow_html=True)
with h2:
    if st.button("← Back to Dashboard", use_container_width=True):
        st.switch_page("dashboard.py")
st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────
try:
    _raw_pos = _demo_positions() if DEMO else _cached_all_positions()
    pos_map  = {p.symbol: p for p in _raw_pos}
except Exception:
    pos_map = {}

all_syms = (["AAPL","MSFT","GOOGL","TSLA"] if DEMO
            else db.get_all_traded_symbols())

all_rows: list[dict] = []
for p in pos_map.values():
    all_rows.append({
        "Symbol":    p.symbol,
        "Qty":       float(p.qty),
        "Avg Entry": float(p.avg_entry_price),
        "Price":     float(p.current_price),
        "Mkt Value": float(p.market_value),
        "P&L ($)":  float(p.unrealized_pl),
        "P&L (%)":  float(p.unrealized_plpc) * 100,
    })

# ── Summary metrics ───────────────────────────────────────────────────────────
total_value = sum(r["Mkt Value"] for r in all_rows)
total_pnl   = sum(r["P&L ($)"]  for r in all_rows)
cost_basis  = total_value - total_pnl
total_pct   = (total_pnl / cost_basis * 100) if cost_basis != 0 else 0.0

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Open Positions",  str(len(all_rows)))
m2.metric("Total Mkt Value", f"${total_value:,.2f}")
m3.metric("Cost Basis",      f"${cost_basis:,.2f}")
m4.metric("Unrealized P&L",  f"${total_pnl:+,.2f}",
          delta=f"{total_pct:+.2f}%",
          delta_color="normal" if total_pnl >= 0 else "inverse")
winners = sum(1 for r in all_rows if r["P&L ($)"] > 0)
m5.metric("Winners / Losers", f"{winners} / {len(all_rows)-winners}")
st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
if all_rows:
    cl, cm, cr = st.columns([2, 2, 1])

    with cl:
        st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                    'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">'
                    'P&L by Position</p>', unsafe_allow_html=True)
        df_pnl = pd.DataFrame(all_rows).sort_values("P&L ($)")
        bar_colors = ["#00c896" if v >= 0 else "#ff4b4b" for v in df_pnl["P&L ($)"]]
        fig_pnl = go.Figure(go.Bar(
            x=df_pnl["Symbol"], y=df_pnl["P&L ($)"],
            marker_color=bar_colors, marker_opacity=0.85,
            hovertemplate="<b>%{x}</b><br>P&L: $%{y:+,.2f}<extra></extra>"))
        fig_pnl.update_layout(**_CHART, height=220)
        fig_pnl.update_yaxes(tickprefix="$", tickformat="+,.0f")
        st.plotly_chart(fig_pnl, use_container_width=True, config=_NO_TB)

    with cm:
        st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                    'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">'
                    'Allocation by Symbol</p>', unsafe_allow_html=True)
        df_alloc = pd.DataFrame(all_rows)
        fig_pie = go.Figure(go.Pie(
            labels=df_alloc["Symbol"], values=df_alloc["Mkt Value"],
            hole=0.4, marker=dict(colors=_PIE_COLORS),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>$%{value:,.2f} (%{percent})<extra></extra>"))
        fig_pie.update_layout(
            paper_bgcolor="#0a0e1a", font=dict(color="#e2e8f0", size=10),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=0, r=0, t=10, b=0), height=220)
        st.plotly_chart(fig_pie, use_container_width=True, config=_NO_TB)

    with cr:
        st.markdown('<p style="font-size:0.68rem;font-weight:600;color:#00d4aa;'
                    'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">'
                    'By Strategy</p>', unsafe_allow_html=True)
        strat_vals: dict[str, float] = {}
        for strat_key in list(STRATEGIES.keys()) + ["manual"]:
            total = 0.0
            if DEMO:
                total = sum(r.get("Mkt Value", 0) for r in _DEMO_STRAT_POS.get(strat_key, []))
            else:
                for sym in all_syms:
                    qty = db.get_strategy_holding(sym, strat_key)
                    if qty > 0:
                        p = pos_map.get(sym)
                        price = float(p.current_price) if p else 0.0
                        total += qty * price
            if total > 0:
                strat_vals[strat_key.upper()] = total

        if strat_vals:
            fig_s = go.Figure(go.Pie(
                labels=list(strat_vals.keys()), values=list(strat_vals.values()),
                hole=0.4,
                marker=dict(colors=[_STRAT_CLR.get(k.lower(), "#74b9ff")
                                    for k in strat_vals.keys()]),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>$%{value:,.2f}<extra></extra>"))
            fig_s.update_layout(
                paper_bgcolor="#0a0e1a", font=dict(color="#e2e8f0", size=10),
                legend=dict(bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=0, r=0, t=10, b=0), height=220)
            st.plotly_chart(fig_s, use_container_width=True, config=_NO_TB)
        else:
            st.caption("No strategy data.")

    st.divider()
else:
    st.info("No open positions to display.")

# ── Tabs by strategy ──────────────────────────────────────────────────────────
_FMT = {"Qty":"{:.0f}","Avg Entry":"${:.2f}","Price":"${:.2f}",
        "Mkt Value":"${:,.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"}

STRAT_TABS = ["All", "RSI", "MACD", "Bollinger", "EMA Cross", "Manual"]
STRAT_KEYS = [None,  "rsi", "macd", "bollinger",  "ema_crossover", "manual"]
tabs = st.tabs(STRAT_TABS)

trades_all = [] if DEMO else db.get_recent_trades(limit=500)

for tab, strat_key in zip(tabs, STRAT_KEYS):
    with tab:
        if strat_key is None:
            if all_rows:
                df_all = pd.DataFrame(all_rows)
                st.dataframe(
                    df_all.style
                        .format(_FMT)
                        .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                    use_container_width=True, hide_index=True, height=420)
            else:
                st.caption("No open positions.")
        else:
            # Build per-strategy rows
            if DEMO:
                rows = _DEMO_STRAT_POS.get(strat_key, [])
            else:
                rows = []
                for sym in all_syms:
                    qty = db.get_strategy_holding(sym, strat_key)
                    if qty > 0:
                        p = pos_map.get(sym)
                        if p is None:
                            continue
                        avg_entry = float(p.avg_entry_price)
                        price     = float(p.current_price)
                        mkt_val   = qty * price
                        pnl       = qty * (price - avg_entry) if avg_entry else 0.0
                        pnl_pct   = (pnl / (qty * avg_entry) * 100) if avg_entry else 0.0
                        rows.append({
                            "Symbol":    sym,
                            "Qty":       round(qty, 4),
                            "Avg Entry": round(avg_entry, 2),
                            "Price":     round(price, 2),
                            "Mkt Value": round(mkt_val, 2),
                            "P&L ($)":  round(pnl, 2),
                            "P&L (%)":  round(pnl_pct, 2),
                        })

            if rows:
                df_s = pd.DataFrame(rows)
                t_left, t_right = st.columns([3, 2])
                with t_left:
                    st.dataframe(
                        df_s.style.format(_FMT)
                            .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                        use_container_width=True, hide_index=True, height=300)

                with t_right:
                    strat_trades = [t for t in trades_all
                                    if t.get("strategy") == strat_key]
                    if strat_trades:
                        df_t = pd.DataFrame(strat_trades)
                        buys_s  = len(df_t[df_t["side"] == "buy"])
                        sells_s = len(df_t[df_t["side"] == "sell"])
                        a1, a2 = st.columns(2)
                        a1.metric("Buys",  str(buys_s))
                        a2.metric("Sells", str(sells_s))

                        # Mini P&L bar per symbol for this strategy
                        if {"symbol","side","quantity","actual_price"}.issubset(df_t.columns):
                            sym_pnl: dict[str, float] = {}
                            for sym_t in df_t["symbol"].unique():
                                st_sym = df_t[df_t["symbol"] == sym_t]
                                bought = st_sym[st_sym["side"]=="buy"]["quantity"].sum()
                                sold   = st_sym[st_sym["side"]=="sell"]["quantity"].sum()
                                avg_b  = (st_sym[st_sym["side"]=="buy"]["actual_price"] *
                                          st_sym[st_sym["side"]=="buy"]["quantity"]).sum()
                                avg_s  = (st_sym[st_sym["side"]=="sell"]["actual_price"] *
                                          st_sym[st_sym["side"]=="sell"]["quantity"]).sum()
                                sym_pnl[sym_t] = avg_s - avg_b
                            spnl_items = sorted(sym_pnl.items(), key=lambda x: x[1])
                            fig_sp = go.Figure(go.Bar(
                                x=[x[0] for x in spnl_items],
                                y=[x[1] for x in spnl_items],
                                marker_color=["#00c896" if v >= 0 else "#ff4b4b"
                                              for _, v in spnl_items],
                                hovertemplate="<b>%{x}</b><br>Realized P&L: $%{y:+,.2f}<extra></extra>"))
                            fig_sp.update_layout(**_CHART, height=150,
                                                 title=dict(text="Realized P&L by Symbol",
                                                            font=dict(size=10)))
                            fig_sp.update_yaxes(tickprefix="$", tickformat="+,.0f")
                            st.plotly_chart(fig_sp, use_container_width=True, config=_NO_TB)
                    else:
                        st.caption("No trade history for this strategy.")

                # Recent trade history table
                if strat_trades:
                    st.markdown("**Trade History**")
                    df_th = pd.DataFrame(strat_trades)
                    cols_show = [c for c in
                                 ["timestamp","symbol","side","quantity","actual_price","notes"]
                                 if c in df_th.columns]
                    _LS = {"buy":"color:#00c896;font-weight:600","sell":"color:#ff4b4b;font-weight:600"}
                    styled = df_th[cols_show].style
                    if "side" in cols_show:
                        styled = styled.map(lambda v: _LS.get(v,""), subset=["side"])
                    if "actual_price" in cols_show:
                        styled = styled.format({"actual_price":"${:.2f}","quantity":"{:.0f}"},
                                               na_rep="—")
                    st.dataframe(styled, use_container_width=True,
                                 hide_index=True, height=200)
            else:
                st.caption(f"No active {(strat_key or '').upper()} positions.")

st.divider()
st.markdown("**Submitted Orders**")
order_rows = [] if DEMO else db.get_recent_order_requests(limit=100)
if order_rows:
    df_o = pd.DataFrame(order_rows)
    cols_o = [c for c in [
        "timestamp", "strategy", "symbol", "side", "quantity",
        "requested_price", "estimated_value", "status", "notes", "alpaca_order_id"
    ] if c in df_o.columns]
    fmt_o = {
        "quantity": "{:.0f}",
        "requested_price": "${:.2f}",
        "estimated_value": "${:,.2f}",
    }
    st.dataframe(
        df_o[cols_o].style.format(fmt_o, na_rep="-"),
        use_container_width=True, hide_index=True, height=260)
else:
    st.caption("No submitted orders recorded yet.")
