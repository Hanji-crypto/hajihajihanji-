"""Form 4 提出日 × 騰落率 × 指標推移 × 速報(8-K) を一画面で毎日比較するダッシュボード。

起動: streamlit run app_compare_dashboard.py
"""
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

import compare_logic as cl

DB_PATH = "insider.db"
BG, PANEL, GRID, TEXT = "#0d1117", "#161b22", "#21262d", "#E0E3EB"
UP, DOWN, ACCENT, WARN = "#00E676", "#FF1744", "#58a6ff", "#FFB300"

st.set_page_config(page_title="Insider Daily Compare", layout="wide")
st.markdown(
    f"""<style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{background-color:{BG} !important;}}
    html, body, p, h1, h2, h3, h4, label, span, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{color:#e6edf3 !important;}}
    </style>""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- データ取得
@st.cache_data(ttl=300)
def load_trades() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT filing_date, insider, ticker, company, total_value, filing_url FROM insider_trades", conn
        )
    finally:
        conn.close()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df


def _close_series(frame: pd.DataFrame) -> pd.Series:
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s


@st.cache_data(ttl=1800)
def load_prices(tickers: tuple, start: str) -> dict:
    """終値を一括取得（API負荷を抑えるためまとめて1回）。"""
    out: dict[str, pd.Series] = {}
    if not tickers:
        return out
    try:
        data = yf.download(list(tickers), start=start, group_by="ticker", progress=False, threads=True, auto_adjust=True)
    except Exception:
        return out
    for t in tickers:
        try:
            frame = data if len(tickers) == 1 else data[t]
            s = _close_series(frame)
            if not s.empty:
                out[t] = s
        except Exception:
            continue
    return out


@st.cache_data(ttl=1800)
def load_detail(ticker: str, start: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


@st.cache_data(ttl=3600)
def load_8k(ticker: str, since: str) -> pd.DataFrame:
    """速報情報(8-K)。SECへ接続できない環境では空を返し、画面は他の情報だけで表示する。"""
    try:
        from edgar import Company, set_identity

        set_identity("OptionScreener eae270@gmail.com")
        filings = Company(ticker).get_filings(form="8-K")
        rows = []
        for f in filings:
            fd = pd.Timestamp(str(f.filing_date)).normalize()
            if fd < pd.Timestamp(since):
                break  # 新しい順に並ぶので、範囲外に出たら終了
            label, high = cl.items_to_label(getattr(f, "items", None))
            rows.append((fd, label, high, getattr(f, "filing_url", None) or getattr(f, "homepage_url", None)))
        return pd.DataFrame(rows, columns=["date", "label", "high", "url"])
    except Exception:
        return pd.DataFrame(columns=["date", "label", "high", "url"])


def style(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", plot_bgcolor=BG, paper_bgcolor=PANEL, height=height,
        margin=dict(l=40, r=15, t=35, b=30), font=dict(color=TEXT),
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center", bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


# ---------------------------------------------------------------- 条件
st.title("📊 Insider Daily Compare")
st.caption("Form 4 提出日の終値を 0% として、提出後の騰落率・指標・速報(8-K)を並べて比較します。")

try:
    raw = load_trades()
except Exception as e:
    st.error(f"データベースの読み込みに失敗しました: {e}")
    st.stop()

agg_all = cl.aggregate_filings(raw)
if agg_all.empty:
    st.warning("表示できるデータがありません。")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
with c1:
    span = st.selectbox("対象の提出日", [7, 14, 30, 60, 90], index=2, format_func=lambda d: f"直近{d}日")
with c2:
    min_value = st.select_slider("最低購入額", [0, 50_000, 100_000, 250_000, 500_000, 1_000_000], value=100_000,
                                 format_func=lambda v: f"${v:,.0f}")
with c3:
    top_n = st.slider("比較する件数(購入額上位)", 3, 20, 10)
with c4:
    max_days = st.slider("提出後の追跡日数", 5, 60, 20)

latest_filing = agg_all["filing_date"].max()
agg = agg_all[(agg_all["filing_date"] >= latest_filing - pd.Timedelta(days=span)) & (agg_all["value"] >= min_value)]
if agg.empty:
    st.info("条件に合うデータがありません。期間を広げるか、最低購入額を下げてください。")
    st.stop()

top = agg.nlargest(top_n, "value").reset_index(drop=True)
tickers = tuple(sorted(agg["ticker"].unique()))
start = (agg["filing_date"].min() - timedelta(days=5)).strftime("%Y-%m-%d")

with st.spinner("株価を取得中..."):
    prices = load_prices(tickers, start)

rets_all = cl.returns_since_filing(prices, agg, max_days)
rets_top = cl.returns_since_filing(prices, top, max_days)
if rets_all.empty:
    st.warning("株価を取得できませんでした。時間をおいて再読み込みしてください。")
    st.stop()

# ---------------------------------------------------------------- A. KPI
k = cl.kpis(agg, rets_all)
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("最新の提出日", f"{k['latest_date']:%Y-%m-%d}")
m2.metric("その日の新規 / 購入額", f"{k['n_latest']} 件 / ${k['value_latest']:,.0f}")
m3.metric("対象の提出件数", f"{k['n_total']} 件")
m4.metric("提出後の平均騰落率", "N/A" if k["avg_ret"] is None else f"{k['avg_ret']:+.2f}%")
m5.metric("勝率(プラスの割合)", "N/A" if k["win_rate"] is None else f"{k['win_rate']:.0f}%")

# ---------------------------------------------------------------- B. 提出日=0% の騰落率カーブ
st.subheader("① 提出日を0%とした騰落率の推移（購入額上位）")
fig = go.Figure()
for (t, fd), g in rets_top.groupby(["ticker", "filing_date"]):
    fig.add_trace(go.Scatter(x=g["day"], y=g["ret"], mode="lines", name=cl.label_of(t, fd),
                             line=dict(width=1.4), opacity=0.8,
                             hovertemplate="%{fullData.name}<br>D+%{x}: %{y:+.2f}%<extra></extra>"))
mean_line = cl.cohort_mean(rets_all)
fig.add_trace(go.Scatter(x=mean_line.index, y=mean_line.values, mode="lines", name="全体平均",
                         line=dict(color="#FFFFFF", width=3.5)))
w_line = cl.cohort_mean(rets_all, weighted=True)
fig.add_trace(go.Scatter(x=w_line.index, y=w_line.values, mode="lines", name="購入額加重平均",
                         line=dict(color=WARN, width=3, dash="dash")))
fig.add_hline(y=0, line_color="#8b949e", line_width=1)
fig.update_xaxes(title="提出後の経過取引日 (D+n)")
fig.update_yaxes(title="騰落率 (%)", ticksuffix="%")
st.plotly_chart(style(fig, 430), width="stretch")

# ---------------------------------------------------------------- C. ヒートマップ
st.subheader("② 日次ヒートマップ（縦に読めば同じ経過日で比較できる）")
hm = cl.heat_matrix(rets_all, top_n=top_n)
if not hm.empty:
    zmax = float(np.nanpercentile(np.abs(hm.values), 95)) or 1.0
    heat = go.Figure(go.Heatmap(
        z=hm.values, x=[f"D+{c}" for c in hm.columns], y=hm.index, zmin=-zmax, zmax=zmax,
        colorscale=[[0, DOWN], [0.5, PANEL], [1, UP]], colorbar=dict(title="%", ticksuffix="%"),
        hovertemplate="%{y} %{x}: %{z:+.2f}%<extra></extra>",
    ))
    heat.update_yaxes(autorange="reversed")
    st.plotly_chart(style(heat, max(300, 26 * len(hm) + 80)), width="stretch")

# ---------------------------------------------------------------- D. 銘柄の詳細 + 速報
st.subheader("③ 銘柄詳細：株価・RSI・出来高 と 速報(8-K) を提出日に重ねる")
options = [f"{cl.label_of(r.ticker, r.filing_date)}  (${r.value:,.0f})" for r in top.itertuples()]
choice = st.selectbox("銘柄を選択", options)
sel = top.iloc[options.index(choice)]
ticker, f_date = sel["ticker"], sel["filing_date"]

d_start = (f_date - timedelta(days=45)).strftime("%Y-%m-%d")
detail = load_detail(ticker, d_start)
k8 = load_8k(ticker, d_start)

if detail is None or detail.empty:
    st.warning("この銘柄の株価を取得できませんでした。")
else:
    close = detail["Close"]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
    fig.add_trace(go.Scatter(x=close.index, y=close, name="終値", line=dict(color=ACCENT, width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=close.index, y=close.rolling(20).mean(), name="20日平均",
                             line=dict(color=WARN, width=1, dash="dash")), row=1, col=1)
    # 提出日の縦線（全パネル共通）
    for yref in ("y domain", "y2 domain", "y3 domain"):
        fig.add_shape(type="line", x0=f_date, x1=f_date, y0=0, y1=1, xref="x", yref=yref,
                      line=dict(color="#D500F9", width=1.5, dash="dot"))
    fig.add_annotation(x=f_date, y=1, xref="x", yref="y domain", text="Form 4 提出", showarrow=False, yshift=12,
                       font=dict(color="#D500F9", size=11))
    # 速報(8-K)マーカー
    if not k8.empty:
        k8 = k8[k8["date"] >= close.index.min()]
        yy = close.reindex(close.index.union(k8["date"])).ffill().reindex(k8["date"]).values
        fig.add_trace(go.Scatter(
            x=k8["date"], y=yy, mode="markers", name="速報(8-K)",
            marker=dict(size=[14 if h else 9 for h in k8["high"]], symbol="diamond",
                        color=[WARN if h else "#8b949e" for h in k8["high"]], line=dict(color="#fff", width=1)),
            text=[f"{d:%m/%d} {lbl}" for d, lbl in zip(k8["date"], k8["label"])], hoverinfo="text"), row=1, col=1)
    rsi = cl.rsi(close)
    fig.add_trace(go.Scatter(x=rsi.index, y=rsi, name="RSI(14)", line=dict(color="#FF9100", width=1.4)), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,23,68,.4)", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(0,230,118,.4)", row=2, col=1)
    if "Volume" in detail:
        colors = [UP if c >= o else DOWN for c, o in zip(detail["Close"], detail["Open"])]
        fig.add_trace(go.Bar(x=detail.index, y=detail["Volume"], name="出来高", marker_color=colors), row=3, col=1)
    fig.update_layout(xaxis3_rangeslider_visible=False)
    st.plotly_chart(style(fig, 560), width="stretch")

    # 速報の一覧（提出日からの相対日つき）
    st.markdown("**速報(8-K)一覧**" + ("" if not k8.empty else "　— 取得できませんでした（SEC接続なし/該当なし）"))
    if not k8.empty:
        table = k8.sort_values("date", ascending=False).copy()
        table["提出日からの日数"] = (table["date"] - f_date).dt.days.map(lambda d: f"{d:+d}日")
        table["重要度"] = table["high"].map({True: "★重要", False: ""})
        st.dataframe(
            table.rename(columns={"date": "日付", "label": "内容", "url": "EDGAR"})[["日付", "提出日からの日数", "内容", "重要度", "EDGAR"]],
            hide_index=True, width="stretch",
            column_config={"日付": st.column_config.DateColumn(format="YYYY-MM-DD"), "EDGAR": st.column_config.LinkColumn("EDGAR")},
        )
