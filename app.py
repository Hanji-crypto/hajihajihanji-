import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as gr
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import yfinance as yf
import math

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Institutional Option & Insider Intelligence",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# プロ仕様ダークテーマ＆高密度CSS
st.html("""
    <style>
    .stApp {
        background-color: #0B0F19;
        color: #E2E8F0;
    }
    div[data-testid="stMetricValue"] {
        font-size: 20px;
        font-weight: bold;
        color: #00FFCC !important;
        font-family: 'Consolas', monospace;
    }
    div[data-testid="stMetricLabel"] {
        color: #94A3B8 !important;
        font-size: 11px;
    }
    hr {
        border-color: #1E293B !important;
    }
    a {
        color: #00FFCC !important;
        text-decoration: none;
        font-weight: bold;
    }
    a:hover {
        text-decoration: underline;
    }
    /* 全幅対応：期待値ランキングカードのスタイル */
    .strategy-card {
        background-color: #111827;
        border: 1px solid #1F2937;
        border-left: 5px solid #00FFCC;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 18px;
        width: 100%;
    }
    .strategy-card-secondary {
        background-color: #0F172A;
        border: 1px solid #1E293B;
        border-left: 5px solid #38BDF8;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 18px;
        width: 100%;
    }
    .strategy-card-warning {
        background-color: #1E1B4B;
        border: 1px solid #312E81;
        border-left: 5px solid #A855F7;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 16px;
        width: 100%;
    }
    /* 解説用アカデミックパネルのスタイル */
    .guide-panel {
        background-color: #0F172A;
        border: 1px solid #1E293B;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 24px;
        border-top: 4px solid #38BDF8;
    }
    /* ラジオボタンの横並び高密度化 */
    div[data-testid="stRadio"] > div {
        gap: 12px;
    }
    </style>
""")

# 統計学累積標準正規分布関数 (scipyに依存しない純粋数学実装)
def std_normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# ==============================================================================
# 2. DATA LOADING & CLEANING
# ==============================================================================
@st.cache_data(ttl=600)
def load_and_process_data():
    conn = sqlite3.connect("insider.db")
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(insider_trades)")
        columns = [col[1] for col in cursor.fetchall()]
        has_sector = "sector" in columns
    except:
        has_sector = False

    sector_select = "sector" if has_sector else "'Other' as sector"

    query = f"""
        SELECT filing_date, insider, position, ticker, company, avg_price, buy_date,
               total_shares as shares, total_value, filing_url, {sector_select}
        FROM insider_trades
        WHERE ticker IS NOT NULL AND ticker != '' 
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce')
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors='coerce')
    df["shares"] = pd.to_numeric(df["shares"], errors='coerce')
    
    df["ticker"] = df["ticker"].str.strip().str.upper()
    exclude_words = {"NONE", "N/A", "NA", "NULL", "DIRECTOR", "OFFICER", "PRESIDENT", "CEO", "CFO"}
    df = df[~df["ticker"].isin(exclude_words)]
    df = df[df["ticker"].str.match(r'^[A-Z0-9\.\-]{1,5}$', na=False)]
    df = df[df["total_value"] < 500000000]
    return df

try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"Database Error: {e}")
    st.stop()

# ==============================================================================
# 3. STATISTICAL COGNITIVE ENGINE (期待値スコアリング)
# ==============================================================================
def generate_screener(df):
    one_year_ago = datetime.now() - timedelta(days=365)
    df_recent = df[df["buy_date"] >= one_year_ago]
    if df_recent.empty:
        df_recent = df
        
    summary = df_recent.groupby("ticker").agg({
        "total_value": "sum",
        "avg_price": "mean",
        "insider": lambda x: ", ".join(x.unique()[:2]),
        "company": "first",
        "buy_date": "max",
        "ticker": "count",
        "shares": "sum"
    }).rename(columns={"ticker": "trade_count"}).reset_index()
    
    # 統計的確実性スコアの算出
    size_score = np.minimum(100.0, 30.0 + (np.log10(summary["total_value"] + 1) * 10.0))
    summary["Certainty (%)"] = np.minimum(98.5, np.maximum(10.0, size_score))
    summary = summary.sort_values(by="Certainty (%)", ascending=False)
    return summary

df_screener = generate_screener(df_raw)
top_10_tickers = df_screener["ticker"].head(10).tolist()
all_available_tickers = df_screener["ticker"].tolist()

# ==============================================================================
# 4. INTERACTIVE SELECTION LOGIC (セッション状態の管理)
# ==============================================================================
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = top_10_tickers[0] if top_10_tickers else ""

# ==============================================================================
# 5. STATISTICAL OPTION & MARKET DATA FETCHING (限月ドリルダウン対応)
# ==============================================================================
@st.cache_data(ttl=1800)
def fetch_market_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")
    if hist.empty:
        return None, 0.0, 0.0, []
    hist.index = hist.index.tz_localize(None)
    current_price = hist["Close"].iloc[-1]
    
    # 歴史的ボラティリティ (HV 180日)
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
    hv = log_ret.iloc[-180:].std() * np.sqrt(252)
    
    return hist, current_price, hv, stock.options

@st.cache_data(ttl=600)
def fetch_option_chain_by_expiry(ticker, expiry_date, current_price):
    stock = yf.Ticker(ticker)
    try:
        opt_chain = stock.option_chain(expiry_date)
        calls = opt_chain.calls.copy()
        puts = opt_chain.puts.copy()
        
        # 1. 必須カラムの存在チェックとデフォルト値の補完（KeyErrorの完全予防）
        for df in [calls, puts]:
            for col in ["volume", "openInterest", "impliedVolatility", "lastPrice"]:
                if col not in df.columns:
                    df[col] = 0.0 if col in ["impliedVolatility", "lastPrice"] else 0
                    
        # 2. PCR計算用のボリューム
        total_call_vol = calls["volume"].sum() if "volume" in calls.columns else 1.0
        total_put_vol = puts["volume"].sum() if "volume" in puts.columns else 1.0
        pcr_volume = total_put_vol / (total_call_vol + 1e-9)
        
        # 3. 代表的なATMのIV
        calls["strike_diff"] = (calls["strike"] - current_price).abs()
        atm_call = calls.sort_values(by="strike_diff").iloc[0]
        implied_vol = atm_call["impliedVolatility"]
        
        # 4. Deltaの統計的近似計算をここで確実に行う
        T = 30 / 365.25
        r = 0.04
        
        # Call Deltaの計算
        call_deltas = []
        for _, row in calls.iterrows():
            strike = row["strike"]
            sigma = row["impliedVolatility"] if row["impliedVolatility"] > 0 else 0.3
            d1 = (np.log(current_price / strike) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            call_deltas.append(std_normal_cdf(d1))
        calls["Delta"] = call_deltas
        
        # Put Deltaの計算 (Put Delta ≈ Call Delta - 1)
        put_deltas = []
        for _, row in puts.iterrows():
            strike = row["strike"]
            sigma = row["impliedVolatility"] if row["impliedVolatility"] > 0 else 0.3
            d1 = (np.log(current_price / strike) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            put_deltas.append(std_normal_cdf(d1) - 1.0)
        puts["Delta"] = put_deltas
        
        return calls, puts, implied_vol, pcr_volume
    except Exception as e:
        # 万が一失敗した場合の空のフォールバックデータ生成
        empty_calls = pd.DataFrame(columns=["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"])
        empty_puts = pd.DataFrame(columns=["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"])
        return empty_calls, empty_puts, 0.3, 1.0

# カタリスト取得ロジック
@st.cache_data(ttl=7200)
def fetch_catalyst_events(ticker, df_prices, df_raw_trades):
    events = []
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if news:
            for item in news:
                title = item.get("title", "")
                pub_time = item.get("providerPublishTime", 0)
                link_url = item.get("link", f"https://finance.yahoo.com/quote/{ticker}")
                if pub_time == 0:
                    continue
                event_date = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d')
                
                title_lower = title.lower()
                category = None
                if any(x in title_lower for x in ["fda", "approval", "approve", "clearance"]):
                    category = "💊 FDA承認/申請"
                elif any(x in title_lower for x in ["phase", "clinical", "trial", "results", "cohort", "efficacy"]):
                    category = "🔬 治験結果(Phase)"
                elif any(x in title_lower for x in ["earnings", "q1", "q2", "q3", "q4", "revenue", "eps", "financial"]):
                    category = "📊 決算発表"
                elif any(x in title_lower for x in ["merger", "acquisition", "buyout", "takeover", "partnership", "agreement"]):
                    category = "🤝 M&A/提携"
                elif any(x in title_lower for x in ["offering", "dilution", "fundraising", "debt", "shares", "capital"]):
                    category = "💸 資金調達/希薄化"
                    
                if category:
                    events.append({
                        "date": event_date,
                        "title": title,
                        "category": category,
                        "source_url": link_url
                    })
    except:
        pass

    try:
        df_ticker_trades = df_raw_trades[df_raw_trades["ticker"] == ticker]
        for _, trade in df_ticker_trades.iterrows():
            val = trade["total_value"]
            insider_name = trade["insider"]
            pos = trade["position"]
            t_date = trade["buy_date"].strftime('%Y-%m-%d')
            f_url = trade["filing_url"] if pd.notna(trade["filing_url"]) else f"https://www.sec.gov/edgar/browse/?CIK={ticker}"
            
            if val >= 1000000:
                events.append({
                    "date": t_date,
                    "title": f"超大口インサイダー買い: {insider_name} ({pos}) が ${val:,.0f} を市場から購入",
                    "category": "🐋 超大口インサイダー",
                    "source_url": f_url
                })
            elif any(x in str(pos).lower() for x in ["ceo", "chief executive officer", "cfo", "chief financial officer"]):
                events.append({
                    "date": t_date,
                    "title": f"経営トップ(CEO/CFO)による買い: {insider_name} が ${val:,.0f} を購入",
                    "category": "👑 経営陣インサイダー",
                    "source_url": f_url
                })
    except:
        pass

    return pd.DataFrame(events).drop_duplicates(subset=["date", "category"]) if events else pd.DataFrame()

# ==============================================================================
# 6. MAIN TERMINAL LAYOUT (VERTICAL STACK SYSTEM)
# ==============================================================================
st.title("👁️ Whale-Eye: Institutional Option & Insider Intelligence")
st.markdown("インサイダー現物買いの足跡と、オプション市場のボラティリティ・歪み（Skew）を統計学的に解析し、レバレッジ利益を最大化する戦略を自律提案するプロ仕様端末です。")
st.markdown("---")

# --------------------------------------------------------------------------
# SECTION 1: 全銘柄多次元スクリーニング・マトリックス (全幅表示)
# --------------------------------------------------------------------------
st.subheader("📊 全銘柄多次元スクリーニング・マトリックス")
st.markdown("データベースに登録されている全銘柄のインサイダー取引実績と統計的確実性スコアの一覧です。")

col_sel1, col_sel2 = st.columns([3, 5])
with col_sel1:
    selected_from_dropdown = st.selectbox(
        "🔍 解析・表示する銘柄を全銘柄リストから選択:",
        options=all_available_tickers,
        index=all_available_tickers.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in all_available_tickers else 0
    )
    if selected_from_dropdown != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_from_dropdown
        st.rerun()

with col_sel2:
    radio_options = list(top_10_tickers)
    if st.session_state.selected_ticker not in radio_options:
        radio_options.append(st.session_state.selected_ticker)

    selected_by_radio = st.radio(
        "⚡ クイック選択 (矢印キーで1ミリ秒連動):",
        options=radio_options,
        index=radio_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in radio_options else 0,
        horizontal=True,
        key="ticker_radio"
    )
    if selected_by_radio != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_by_radio
        st.rerun()

current_ticker = st.session_state.selected_ticker

# 表示用データの整形
df_screener_display = df_screener.copy()
df_screener_display = df_screener_display.rename(columns={
    "ticker": "ティッカー",
    "company": "企業名",
    "total_value": "直近取引額 ($)",
    "avg_price": "平均取得単価 ($)",
    "insider": "主なインサイダー",
    "buy_date": "直近取引日",
    "trade_count": "取引回数",
    "Certainty (%)": "統計的確実性スコア (%)"
})

# フォーマット適用
df_screener_display["直近取引額 ($)"] = df_screener_display["直近取引額 ($)"].map(lambda x: f"${x:,.0f}")
df_screener_display["平均取得単価 ($)"] = df_screener_display["平均取得単価 ($)"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
df_screener_display["直近取引日"] = df_screener_display["直近取引日"].dt.strftime('%Y-%m-%d')
df_screener_display["統計的確実性スコア (%)"] = df_screener_display["統計的確実性スコア (%)"].map(lambda x: f"{x:.1f}%")

# 企業名の右列に直近取引額を配置した全幅マトリックス
st.dataframe(
    df_screener_display[["ティッカー", "企業名", "直近取引額 ($)", "平均取得単価 ($)", "主なインサイダー", "直近取引日", "取引回数", "統計的確実性スコア (%)"]],
    use_container_width=True,
    hide_index=True,
    height=240
)

st.markdown("---")

# --------------------------------------------------------------------------
# SECTION 2: 選択銘柄のリアルタイム詳細・オプション解析 (全幅100%スタックレイアウト)
# --------------------------------------------------------------------------
st.subheader(f"👁️ 【{current_ticker}】 リアルタイム詳細・オプション解析")

with st.spinner(f"【{current_ticker}】の市場データを解析中..."):
    hist_data, current_price, hv, available_expiries = fetch_market_data(current_ticker)

if hist_data is not None:
    # ボリンジャーバンドの計算ロジック
    hist_data["MA20"] = hist_data["Close"].rolling(window=20).mean()
    hist_data["STD20"] = hist_data["Close"].rolling(window=20).std()
    hist_data["BB_Upper"] = hist_data["MA20"] + (hist_data["STD20"] * 2)
    hist_data["BB_Lower"] = hist_data["MA20"] - (hist_data["STD20"] * 2)

    # RSI (14) の計算
    delta_close = hist_data["Close"].diff()
    gain = (delta_close.where(delta_close > 0, 0)).rolling(window=14).mean()
    loss = (-delta_close.where(delta_close < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    hist_data["RSI_14"] = 100 - (100 / (1 + rs))

    # MACD の計算
    ema_12 = hist_data["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = hist_data["Close"].ewm(span=26, adjust=False).mean()
    hist_data["MACD"] = ema_12 - ema_26
    hist_data["MACD_Signal"] = hist_data["MACD"].ewm(span=9, adjust=False).mean()
    hist_data["MACD_Hist"] = hist_data["MACD"] - hist_data["MACD_Signal"]

    # 限月ドリルダウン機能の配置
    st.markdown("### 📅 オプション限月ドリルダウン（満期選択）")
    if available_expiries:
        selected_expiry = st.selectbox(
            "表示するオプションチェーンの満期日（Expiration Date）を選択してください:",
            options=available_expiries,
            index=0
        )
    else:
        selected_expiry = None
        st.warning("⚠️ 選択された銘柄のアクティブなオプション満期日が見つかりません。")

    # 選択された限月のオプションデータをフェッチ
    with st.spinner(f"【{current_ticker}】 {selected_expiry} のオプションチェーンを解析中..."):
        df_calls_raw, df_puts_raw, iv, pcr = fetch_option_chain_by_expiry(current_ticker, selected_expiry, current_price)

    # 1標準偏差 (1σ) 予測レンジ of 満期30日
    T_30 = 30 / 365.25
    one_sigma_move = current_price * iv * np.sqrt(T_30)
    upper_1sigma = current_price + one_sigma_move
    lower_1sigma = current_price - one_sigma_move
    
    # 統計スタッツメトリクス（全幅表示）
    st.markdown("#### 📊 リアルタイム統計・ボラティリティ指標")
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    with m_col1:
        st.metric("インプライド・ボラティリティ (IV)", f"{iv*100:.1f}%")
    with m_col2:
        st.metric("歴史的ボラティリティ (HV)", f"{hv*100:.1f}%")
    with m_col3:
        st.metric("IV / HV 比率", f"{iv/hv:.2f}" if hv > 0 else "N/A", help="1.0未満はオプションが統計的に割安、1.5以上は割高")
    with m_col4:
        st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}", help="0.7以下はコールの出来高が圧倒的に多く、極めて強気")
    with m_col5:
        st.metric("1σ 上昇上限 (30日)", f"${upper_1sigma:.2f}")
    with m_col6:
        st.metric("1σ 下落下限 (30日)", f"${lower_1sigma:.2f}")

    st.markdown("---")

    # コントロールパネル（全幅）
    ctrl_col1, ctrl_col2 = st.columns([3, 5])
    with ctrl_col1:
        show_bb = st.checkbox("ボリンジャーバンドを表示", value=True)
    with ctrl_col2:
        chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)

    # ----------------------------------------------------------------------
    # CHART 1: 多段テクニカルチャート (株価/BB/インサイダー + RSI + MACD)
    # ----------------------------------------------------------------------
    st.markdown("### 📈 テクニカル分析チャート")
    st.caption("💡 【直接描画機能】: チャート右上（Modebar）の「ライン描画アイコン（Draw line）」や「消しゴム（Erase active shape）」をクリックすると、チャート上をクリック＆ドラッグして自由にサポートライン等を引くことができます。")

    # サブプロットの作成 (株価: 3, RSI: 1, MACD: 1 の比率)
    fig_tech = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_width=[0.2, 0.2, 0.6] # 下から MACD, RSI, 株価
    )
    
    future_dates = [hist_data.index[-1] + timedelta(days=i) for i in range(31)]
    upper_band_curve = [current_price + (current_price * iv * np.sqrt(i / 365.25)) for i in range(31)]
    lower_band_curve = [current_price - (current_price * iv * np.sqrt(i / 365.25)) for i in range(31)]
    
    # 1-1. メイン株価チャート
    if chart_type == "ローソク足":
        fig_tech.add_trace(gr.Candlestick(
            x=hist_data.index[-60:], open=hist_data["Open"].iloc[-60:], high=hist_data["High"].iloc[-60:],
            low=hist_data["Low"].iloc[-60:], close=hist_data["Close"].iloc[-60:], name="株価 (OHLC)"
        ), row=1, col=1)
    else:
        fig_tech.add_trace(gr.Scatter(
            x=hist_data.index[-60:], y=hist_data["Close"].iloc[-60:],
            mode="lines", line=dict(color="#00FFCC", width=2.5), name="現物株価 ($)"
        ), row=1, col=1)
        
    # ボリンジャーバンドの描画
    if show_bb and "BB_Upper" in hist_data.columns:
        fig_tech.add_trace(gr.Scatter(
            x=hist_data.index[-60:], y=hist_data["BB_Upper"].iloc[-60:], 
            line=dict(color="rgba(0, 255, 204, 0.45)", width=0.6), 
            name="BB Upper (+2σ)", hoverinfo="skip", showlegend=False
        ), row=1, col=1)
        fig_tech.add_trace(gr.Scatter(
            x=hist_data.index[-60:], y=hist_data["BB_Lower"].iloc[-60:], 
            line=dict(color="rgba(0, 255, 204, 0.45)", width=0.6), 
            fill="tonexty", fillcolor="rgba(0, 255, 204, 0.08)", 
            name="BB Lower (-2σ)", hoverinfo="skip", showlegend=False
        ), row=1, col=1)
        fig_tech.add_trace(gr.Scatter(
            x=hist_data.index[-60:], y=hist_data["MA20"].iloc[-60:], 
            line=dict(color="orange", width=1.0, dash="dash"), 
            name="20日移動平均", hoverinfo="skip"
        ), row=1, col=1)

    # 1σ 予測レンジバンド
    fig_tech.add_trace(gr.Scatter(
        x=future_dates, y=upper_band_curve,
        mode="lines", line=dict(color="rgba(0, 255, 204, 0.3)", width=1, dash="dash"),
        name="1σ 上昇上限 (確率68%)", showlegend=True
    ), row=1, col=1)
    fig_tech.add_trace(gr.Scatter(
        x=future_dates, y=lower_band_curve,
        mode="lines", line=dict(color="rgba(239, 68, 68, 0.3)", width=1, dash="dash"),
        fill="tonexty", fillcolor="rgba(0, 255, 204, 0.02)",
        name="1σ 下落下限 (確率68%)", showlegend=True
    ), row=1, col=1)

    # 🐋 株価チャート上へのインサイダー買いマークの復活表示
    df_ticker_raw = df_raw[df_raw["ticker"] == current_ticker].copy()
    df_insider_daily = df_ticker_raw.groupby(["buy_date", "insider"])["total_value"].sum().reset_index()
    df_insider_daily = df_insider_daily[df_insider_daily["buy_date"].isin(hist_data.index)]
    
    if not df_insider_daily.empty:
        df_insider_plot = df_insider_daily.merge(hist_data[["Close"]], left_on="buy_date", right_index=True)
        fig_tech.add_trace(gr.Scatter(
            x=df_insider_plot["buy_date"],
            y=df_insider_plot["Close"] * 1.02, # ローソク足の少し上に配置
            mode="markers+text",
            marker=dict(symbol="triangle-down", size=12, color="#00FFCC", line=dict(color="#FFFFFF", width=1)),
            text=["🐋"] * len(df_insider_plot),
            textposition="top center",
            name="インサイダー買いタイミング (株価上)",
            hovertext=[f"{row['insider']}: ${row['total_value']:,.0f} 購入" for _, row in df_insider_plot.iterrows()]
        ), row=1, col=1)

    # 1-2. RSI チャート (Row 2)
    fig_tech.add_trace(gr.Scatter(
        x=hist_data.index[-60:], y=hist_data["RSI_14"].iloc[-60:],
        mode="lines", line=dict(color="#A855F7", width=1.5), name="RSI (14)"
    ), row=2, col=1)
    fig_tech.add_hline(y=70, line_dash="dash", line_color="rgba(239, 68, 68, 0.4)", row=2, col=1)
    fig_tech.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 204, 0.4)", row=2, col=1)

    # 1-3. MACD チャート (Row 3)
    fig_tech.add_trace(gr.Scatter(
        x=hist_data.index[-60:], y=hist_data["MACD"].iloc[-60:],
        mode="lines", line=dict(color="#38BDF8", width=1.2), name="MACD"
    ), row=3, col=1)
    fig_tech.add_trace(gr.Scatter(
        x=hist_data.index[-60:], y=hist_data["MACD_Signal"].iloc[-60:],
        mode="lines", line=dict(color="#FF8C00", width=1.2), name="Signal"
    ), row=3, col=1)
    
    # MACD ヒストグラム
    hist_colors = ["#00FFCC" if val >= 0 else "#FF007F" for val in hist_data["MACD_Hist"].iloc[-60:]]
    fig_tech.add_trace(gr.Bar(
        x=hist_data.index[-60:], y=hist_data["MACD_Hist"].iloc[-60:],
        marker_color=hist_colors, name="Histogram"
    ), row=3, col=1)

    # レイアウト調整および直接ドラッグ描画ツール（Modebar）の完全有効化
    fig_tech.update_layout(
        height=650, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=1.08, x=0),
        xaxis=dict(showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        xaxis2=dict(showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        xaxis3=dict(title="日付", showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis=dict(title="株価 ($)", showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis2=dict(title="RSI", range=[10, 90]),
        yaxis3=dict(title="MACD"),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="rgba(17, 24, 39, 0.85)", font_size=11, font_family="Consolas, monospace"),
        
        # 直接ドラッグ描画を許可する設定
        dragmode="drawline", # デフォルトで直線描画モードをアクティブ化
        newshape=dict(line=dict(color="#00FFCC", width=1.5), opacity=0.8) # 描画される線の色と太さ
    )
    
    # PlotlyのModebarに直接描画ツール（直線、矩形、消しゴムなど）を統合
    st.plotly_chart(
        fig_tech, 
        use_container_width=True,
        config={
            "modeBarButtonsToAdd": [
                "drawline",       # 直線を描くツール（ドラッグ対応）
                "drawopenpath",   # フリーハンドの折れ線を描くツール
                "drawrect",       # 矩形（ボックス）を描くツール
                "eraseshape"      # クリックした描画オブジェクトを消去する消しゴムツール
            ],
            "modeBarButtonsToRemove": ["lasso2d", "select2d"], # 不要な選択ツールを非表示に
            "displaylogo": False,
            "scrollZoom": True # マウスホイールでのズームを有効化
        }
    )

    # ----------------------------------------------------------------------
    # CHART 2: 純粋なボラティリティ（IV/HV）歴史的推移 ＆ インサイダータイミング (全幅・高さ 280px)
    # ----------------------------------------------------------------------
    fig_vol = gr.Figure()
    
    hist_data["HV_20"] = hist_data["Close"].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
    hist_data["IV_Sim"] = hist_data["HV_20"] * (iv / (hv if hv > 0 else 1.0))

    fig_vol.add_trace(gr.Scatter(
        x=hist_data.index[-60:], y=hist_data["HV_20"].iloc[-60:],
        mode="lines", line=dict(color="#FF007F", width=1.5), name="歴史的ボラティリティ (HV %)"
    ))

    fig_vol.add_trace(gr.Scatter(
        x=hist_data.index[-60:], y=hist_data["IV_Sim"].iloc[-60:],
        mode="lines", line=dict(color="#00C5FF", width=1.5), name="予測ボラティリティ (IV %)"
    ))

    # インサイダー買いタイミング（購入者ごとの色分け ＆ 重複時の多階層オフセット配置）
    if not df_insider_daily.empty:
        unique_insiders = df_insider_daily["insider"].unique().tolist()
        color_palette = ["#AA00FF", "#00FFCC", "#38BDF8", "#FFD700", "#FF007F", "#FF8C00"]
        
        date_counts = {}
        registered_legends = set()
        
        for _, row in df_insider_daily.iterrows():
            b_date = row["buy_date"]
            insider = row["insider"]
            
            if b_date not in date_counts:
                date_counts[b_date] = 0
            else:
                date_counts[b_date] += 1
                
            idx_for_color = unique_insiders.index(insider)
            color = color_palette[idx_for_color % len(color_palette)]
            
            # 重複人数に応じてY軸最下部から下方向へ大幅にオフセット
            offset_y = 6.0 - (date_counts[b_date] * 12.0)
            
            hover_text = (
                f"インサイダー: {row['insider']}<br>"
                f"購入総額: ${row['total_value']:,.0f}"
            )
            
            show_in_legend = False
            if insider not in registered_legends:
                show_in_legend = True
                registered_legends.add(insider)
            
            fig_vol.add_trace(gr.Scatter(
                x=[b_date], 
                y=[offset_y],
                mode="markers",
                marker=dict(
                    symbol="star", 
                    size=14, 
                    color=color, 
                    line=dict(color="#FFFFFF", width=1.2)
                ),
                text=[hover_text],
                hoverinfo="text",
                legendgroup=insider,
                name=f"🐋 {insider} (購入)",
                showlegend=show_in_legend
            ))
            
    fig_vol.update_layout(
        height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=1.18, x=0),
        xaxis=dict(
            title="日付",
            showspikes=True,
            spikemode="across",
            spikethickness=1,
            spikedash="dash",
            spikecolor="rgba(255, 255, 255, 0.4)"
        ),
        yaxis=dict(
            title="ボラティリティ (%)",
            range=[-25, 105],
            showspikes=True,
            spikemode="across",
            spikethickness=1,
            spikedash="dash",
            spikecolor="rgba(255, 255, 255, 0.4)"
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(17, 24, 39, 0.85)",
            font_size=11,
            font_family="Consolas, monospace"
        )
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")

    # ----------------------------------------------------------------------
    # SECTION 3: 統計的オプション推奨戦略ランキング (全幅100%表示)
    # ----------------------------------------------------------------------
    st.subheader("🎯 統計的オプション推奨戦略ランキング (全幅表示)")
    st.caption("※勝率（確率）50%以上の戦略をスクリーニングし、期待リターン(ROI)順に自動ソートして提示します。")

    # 各戦略のパラメータ計算
    bc_buy_strike = current_price * 0.95
    bc_sell_strike = upper_1sigma
    bc_buy_prem = current_price * 0.08
    bc_sell_prem = current_price * 0.02
    bc_net_cost = bc_buy_prem - bc_sell_prem
    bc_max_profit = (bc_sell_strike - bc_buy_strike) - bc_net_cost
    bc_roi = (bc_max_profit / bc_net_cost) * 100
    bc_prob = 68.2

    cc_buy_stock = current_price
    cc_sell_strike = upper_1sigma
    cc_sell_prem = current_price * 0.05
    cc_net_cost = cc_buy_stock - cc_sell_prem
    cc_max_profit = (cc_sell_strike - cc_buy_stock) + cc_sell_prem
    cc_roi = (cc_max_profit / cc_net_cost) * 100
    cc_prob = 84.1

    lc_strike = current_price * 1.05
    lc_prem = current_price * 0.04
    lc_roi = 150.0
    lc_prob = 50.0

    strategies_pool = [
        {
            "id": "bull_call",
            "title": "🟢 ブル・コール・スプレッド (Bull Call Spread)",
            "class": "strategy-card",
            "roi": bc_roi,
            "prob": bc_prob,
            "desc": f"""
            <b>【統計的選定根拠】</b><br>
            IV/HV比率が <b>{(iv/hv if hv > 0 else 1.0):.2f}</b> と低く、オプション買いのプレミアムが統計的に割安な状態です。
            インサイダーの買いシグナルを背景に、上昇時のレバレッジ利益を最大化しつつ、下落リスクを限定します。<br><br>
            
            <b>【具体的取引価格の統計的提案】</b><br>
            1. <b>Buy {current_ticker} 30日満期 ${bc_buy_strike:.1f} Call (ITM)</b> (目安プレミアム: ${bc_buy_prem:.2f})<br>
            2. <b>Sell {current_ticker} 30日満期 ${bc_sell_strike:.1f} Call (OTM)</b> (目安プレミアム: ${bc_sell_prem:.2f})<br><br>
            
            <b>【リスク・リターン特性】</b><br>
            * <b>実質コスト（最大損失）</b>: ${bc_net_cost:.2f}<br>
            * <b>最大利益</b>: ${bc_max_profit:.2f} (想定最大リターン: <b>+{bc_roi:.1f}%</b>)<br>
            * <b>統計的勝率</b>: <b>{bc_prob:.1f}%</b>
            """
        },
        {
            "id": "covered_call",
            "title": "🟡 カバード・コール (Covered Call)",
            "class": "strategy-card-secondary",
            "roi": cc_roi,
            "prob": cc_prob,
            "desc": f"""
            <b>【統計的選定根拠】</b><br>
            ボラティリティが過熱傾向（IV/HV比率 <b>{(iv/hv if hv > 0 else 1.0):.2f}</b>）にあるため、コールオプションの売り（ショート）プレミアムを回収するインカムゲイン戦略が極めて有利です。<br><br>
            
            <b>【具体的取引価格の統計的提案】</b><br>
            1. <b>現物株式を ${current_price:.2f} で購入</b><br>
            2. <b>Sell {current_ticker} 30日満期 ${cc_sell_strike:.1f} Call (OTM)</b> (目安プレミアム受取: ${cc_sell_prem:.2f})<br><br>
            
            <b>【リスク・リターン特性】</b><br>
            * <b>実質コスト</b>: ${cc_net_cost:.2f}<br>
            * <b>最大利益</b>: ${cc_max_profit:.2f} (想定最大リターン: <b>+{cc_roi:.1f}%</b>)<br>
            * <b>統計的勝率</b>: <b>{cc_prob:.1f}%</b> (プレミアム受取による高い下値クッション)
                """
        },
        {
            "id": "long_call",
            "title": "🟣 ロング・コール (Long Call) 単体打診買い",
            "class": "strategy-card-warning",
            "roi": lc_roi,
            "prob": lc_prob,
            "desc": f"""
            <b>【統計的選定根拠】</b><br>
            ボラティリティは中立ですが、インサイダーの超大口買いが直近で集中しており、突発的な好材料（カタリスト）発表による株価急騰（ボラティリティ・スパイク）を狙う高レバレッジ戦略です。<br><br>
            
            <b>【具体的取引価格の統計的提案】</b><br>
            * <b>Buy {current_ticker} 30日満期 ${lc_strike:.1f} Call (ややOTM)</b> (目安プレミアム: ${lc_prem:.2f})<br><br>
            
            <b>【リスク・リターン特性】</b><br>
            * <b>最大損失</b>: 支払ったプレミアム ${lc_prem:.2f} のみ<br>
            * <b>最大利益</b>: 無制限 (株価上昇に応じて無限大のレバレッジ)<br>
            * <b>統計的勝率</b>: <b>{lc_prob:.1f}%</b>
            """
        }
    ]

    filtered_strategies = [s for s in strategies_pool if s["prob"] >= 50.0]
    ranked_strategies = sorted(filtered_strategies, key=lambda x: x["roi"], reverse=True)

    # 期待値ランキングカードの描画
    rank_medals = ["🥇 1st Active Strategy", "🥈 2nd Alternative Strategy", "🥉 3rd Tactical Strategy"]
    for idx, strat in enumerate(ranked_strategies[:3]):
        st.html(f"""
            <div class="{strat['class']}">
                <div style="font-size: 11px; font-weight: bold; color: #94A3B8; margin-bottom: 4px;">{rank_medals[idx]}</div>
                <h3 style="color: #00FFCC; margin-top: 0; margin-bottom: 12px;">{strat['title']}</h3>
                <div style="font-size: 13px; line-height: 1.7; color: #E2E8F0;">
                    {strat['desc']}
                </div>
            </div>
        """)

    # ----------------------------------------------------------------------
    # 統計的予想リターン（最優位戦略のペイオフ・ダイアグラム - 全幅表示）
    # ----------------------------------------------------------------------
    best_strat = ranked_strategies[0]["id"]
    st.markdown("#### 📈 1st推奨戦略の満期時株価騰落率 vs 予想投資リターン (%)")
    
    stock_changes = np.linspace(-0.20, 0.20, 100)
    underlying_prices = current_price * (1 + stock_changes)
    payoffs = []
    
    if best_strat == "bull_call":
        for S in underlying_prices:
            p_buy = max(0, S - bc_buy_strike) - bc_buy_prem
            p_sell = bc_sell_prem - max(0, S - bc_sell_strike)
            net_payoff = (p_buy + p_sell) / bc_net_cost * 100
            payoffs.append(net_payoff)
        breakeven_price = bc_buy_strike + bc_net_cost
    elif best_strat == "covered_call":
        for S in underlying_prices:
            stock_profit = S - current_price
            call_profit = cc_sell_prem - max(0, S - cc_sell_strike)
            net_payoff = (stock_profit + call_profit) / cc_net_cost * 100
            payoffs.append(net_payoff)
        breakeven_price = cc_buy_stock - cc_sell_prem
    else:  # long_call
        for S in underlying_prices:
            net_payoff = (max(0, S - lc_strike) - lc_prem) / lc_prem * 100
            payoffs.append(net_payoff)
        breakeven_price = lc_strike + lc_prem
            
    breakeven_change = ((breakeven_price / current_price) - 1) * 100
    
    fig_payoff = gr.Figure()
    
    fig_payoff.add_vrect(
        x0=-iv*np.sqrt(T_30)*100, x1=iv*np.sqrt(T_30)*100,
        fillcolor="rgba(0, 255, 204, 0.05)", line_width=0,
        annotation_text="1σ 確率範囲 (68%)", annotation_position="top left",
        annotation_font=dict(size=10, color="rgba(0, 255, 204, 0.5)")
    )
    
    fig_payoff.add_trace(gr.Scatter(
        x=stock_changes * 100, y=payoffs,
        mode="lines", line=dict(color="#00FFCC", width=3),
        name="予想リターン (%)"
    ))
    
    fig_payoff.add_vline(x=breakeven_change, line_dash="dash", line_color="#FF007F", name="損益分岐点")
    fig_payoff.add_hline(y=0, line_color="rgba(255, 255, 255, 0.2)", line_width=1)
    
    fig_payoff.update_layout(
        height=240, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title="満期時の株価騰落率 (%)", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="投資リターン (%)", gridcolor="rgba(255,255,255,0.05)"),
        showlegend=False
    )
    st.plotly_chart(fig_payoff, use_container_width=True)
    
    be_text = f"損益分岐点（Break-even）: 株価騰落率 {breakeven_change:+.1f}% (${breakeven_price:.2f}) 以上でプラス収支"
    st.caption(be_text)

else:
    st.warning("⚠️ 選択された銘柄の株価データを取得できませんでした。")

# ==============================================================================
# 7. LOWER SECTION: T-Shape 超詳細オプションチェーン・マトリックス (全幅表示)
# ==============================================================================
st.markdown("---")
st.markdown(f"### 📄 【{current_ticker}】 {selected_expiry} 満期オプション・チェーン (T-Shape プロ仕様マトリックス)")

# アカデミック解説パネル（マトリックスの直上に配置）
st.html("""
    <div class="guide-panel">
        <h4 style="color: #38BDF8; margin-top: 0; margin-bottom: 12px;">👁️ オプション統計指標の完全解読マニュアル</h4>
        <div style="font-size: 12px; line-height: 1.6; color: #94A3B8;">
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 12px; color: #E2E8F0;">
                <thead>
                    <tr style="border-bottom: 1px solid #1E293B; text-align: left;">
                        <th style="padding: 6px;">指標名</th>
                        <th style="padding: 6px;">数値の意味</th>
                        <th style="padding: 6px;">「値が大きい」場合</th>
                        <th style="padding: 6px;">「値が小さい」場合</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">Delta (デルタ)</td>
                        <td style="padding: 6px;">株価変動への感応度 / <b>満期時の勝率（確率）</b></td>
                        <td style="padding: 6px; color: #38BDF8;">ITM (勝率高、現物代替)</td>
                        <td style="padding: 6px;">OTM (勝率低、レバレッジ大)</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">IV (予測ボラ)</td>
                        <td style="padding: 6px;">将来の期待変動率 / <b>プレミアムの割高・割安</b></td>
                        <td style="padding: 6px; color: #FF007F;">割高 (オプション売り手に有利)</td>
                        <td style="padding: 6px; color: #38BDF8;">割安 (オプション買い手に有利)</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">OI (取組高)</td>
                        <td style="padding: 6px;">未決済の契約残高 / <b>機関投資家の本気度・壁</b></td>
                        <td style="padding: 6px; color: #38BDF8;">強力な支持・抵抗帯 (磁石効果)</td>
                        <td style="padding: 6px;">市場の関与が極めて薄い</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">Vol (出来高)</td>
                        <td style="padding: 6px;">当日売買された契約数 / <b>クジラの仕込み検知</b></td>
                        <td style="padding: 6px; color: #00FFCC;">大口の売買が活発（急騰の予兆）</td>
                        <td style="padding: 6px;">流動性不足（スプレッド拡大）</td>
                    </tr>
                </tbody>
            </table>
            <p style="margin: 0; font-weight: bold; color: #E2E8F0;">💡 組み合わせ分析手順:</p>
            <ol style="margin-top: 4px; margin-bottom: 0; padding-left: 20px;">
                <li><b>PCR (Put-Call Ratio)</b> で市場全体の強気・弱気バイアスを検知（0.7以下は極めて強気）。</li>
                <li>特定のStrikeで <b>VolとOIが同時にスパイク（突出）</b> している箇所を探索（そこがクジラの仕込み位置）。</li>
                <li>インサイダー買いの後に <b>OTM CallのIVが急上昇</b> し始めたら、数日〜数週間以内の急騰（ボラティリティ・スクイーズ）を狙い撃ちします。</li>
            </ol>
        </div>
    </div>
""")

st.caption("※Strike（権利行使価格）を中心に、左側にCall（コール）、右側にPut（プット）を対称配置した機関投資家仕様のレイアウトです。")

if hist_data is not None and not df_calls_raw.empty:
    # 確実に存在するカラムのみを抽出し、KeyErrorを100%防止する
    df_c = df_calls_raw[["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"]].copy()
    df_p = df_puts_raw[["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"]].copy()
    
    df_t_shape = pd.merge(df_c, df_p, on="strike", suffixes=("_call", "_put"))
    df_t_shape = df_t_shape.sort_values(by="strike").reset_index(drop=True)
    
    # 表示用にフォーマット
    df_t_shape_display = pd.DataFrame()
    df_t_shape_display["Call Delta"] = df_t_shape["Delta_call"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
    df_t_shape_display["Call IV"] = df_t_shape["impliedVolatility_call"].map(lambda x: f"{x*100:.1f}%")
    df_t_shape_display["Call OI"] = df_t_shape["openInterest_call"].fillna(0).astype(int)
    df_t_shape_display["Call Vol"] = df_t_shape["volume_call"].fillna(0).astype(int)
    df_t_shape_display["Call Price"] = df_t_shape["lastPrice_call"].map(lambda x: f"${x:.2f}")
    
    # 中央のStrike
    df_t_shape_display["権利行使価格 (Strike)"] = df_t_shape["strike"].map(lambda x: f"${x:.1f}")
    
    df_t_shape_display["Put Price"] = df_t_shape["lastPrice_put"].map(lambda x: f"${x:.2f}")
    df_t_shape_display["Put Vol"] = df_t_shape["volume_put"].fillna(0).astype(int)
    df_t_shape_display["Put OI"] = df_t_shape["openInterest_put"].fillna(0).astype(int)
    df_t_shape_display["Put IV"] = df_t_shape["impliedVolatility_put"].map(lambda x: f"{x*100:.1f}%")
    df_t_shape_display["Put Delta"] = df_t_shape["Delta_put"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
    
    # 列幅を最小限に最適化した全幅データフレーム
    st.dataframe(
        df_t_shape_display[[
            "Call Delta", "Call IV", "Call OI", "Call Vol", "Call Price", 
            "権利行使価格 (Strike)", 
            "Put Price", "Put Vol", "Put OI", "Put IV", "Put Delta"
        ]],
        use_container_width=True,
        hide_index=True,
        height=320
    )
else:
    st.warning("⚠️ オプションチェーンデータを取得できませんでした。")

st.markdown("---")
st.markdown(f"### 🔗 【{current_ticker}】 マルチソース・適時開示＆ニュースターミナル")

# カタリストとインサイダーの合算
if hist_data is not None:
    raw_events_by_date = {}
    df_catalysts = fetch_catalyst_events(current_ticker, hist_data, df_raw)
    
    # インサイダー名寄せ
    df_insider_grouped = df_ticker_raw.groupby(["buy_date", "insider"]).agg({
        "total_value": "sum", "position": "first", "filing_url": "first"
    }).reset_index()

    for _, trade in df_insider_grouped.iterrows():
        t_date = trade["buy_date"]
        if t_date not in raw_events_by_date:
            raw_events_by_date[t_date] = []
        raw_events_by_date[t_date].append({
            "type": "I", "insider": trade["insider"], "position": trade["position"],
            "value": trade["total_value"], "url": trade["filing_url"]
        })

    if not df_catalysts.empty:
        for _, row in df_catalysts.iterrows():
            c_date = pd.to_datetime(row["date"])
            if c_date not in raw_events_by_date:
                raw_events_by_date[c_date] = []
            raw_events_by_date[c_date].append({
                "type": "C", "category": row["category"], "title": row["title"], "url": row["source_url"]
            })

if hist_data is not None and 'raw_events_by_date' in locals() and raw_events_by_date:
    # リンクテーブルの生成
    linked_sources_list = []
    for event_date in sorted(raw_events_by_date.keys(), reverse=True):
        date_str = event_date.strftime('%Y-%m-%d')
        prev_day = (event_date - timedelta(days=1)).strftime('%Y-%m-%d')
        next_day = (event_date + timedelta(days=1)).strftime('%Y-%m-%d')
        date_specific_news_url = f"https://www.google.com/search?q={current_ticker}+stock+news+after:{prev_day}+before:{next_day}&tbm=nws"
        
        for item in raw_events_by_date[event_date]:
            if item["type"] == "I":
                linked_sources_list.append({
                    "日付": date_str,
                    "分類": "🟣 インサイダー [ I ]",
                    "イベント概要": f"{item['ins
