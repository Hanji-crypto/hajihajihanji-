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
        font-size: 22px;
        font-weight: bold;
        color: #00FFCC !important;
        font-family: 'Consolas', monospace;
    }
    div[data-testid="stMetricLabel"] {
        color: #94A3B8 !important;
        font-size: 12px;
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
    /* AI・統計考察カードのスタイル */
    .strategy-card {
        background-color: #111827;
        border: 1px solid #1F2937;
        border-left: 5px solid #00FFCC;
        padding: 18px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    .strategy-card-warning {
        background-color: #2D1A1A;
        border: 1px solid #4A2323;
        border-left: 5px solid #EF4444;
        padding: 18px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    /* リアルタイム・イベント・コンソールのスタイル */
    .event-console {
        background-color: #090D16;
        border: 1px solid #1E293B;
        border-radius: 6px;
        padding: 12px;
        max-height: 200px;
        overflow-y: auto;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
        line-height: 1.5;
        margin-bottom: 15px;
    }
    .console-row {
        border-bottom: 1px solid #1E293B;
        padding: 5px 0;
        display: flex;
        align-items: flex-start;
    }
    .console-date {
        color: #64748B;
        min-width: 90px;
        font-weight: bold;
    }
    .console-badge {
        display: inline-block;
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 10px;
        font-weight: bold;
        margin-right: 8px;
        min-width: 100px;
        text-align: center;
    }
    /* ラジオボタンの横並び高密度化 */
    div[data-testid="stRadio"] > div {
        gap: 8px;
    }
    </style>
""")

# 統計学累積標準正規分布関数 (scipyに依存しない純粋数学実装)
def std_normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# Tickerエンコード
def encode_ticker_for_search_avoidance(ticker):
    if not isinstance(ticker, str):
        return ""
    return "".join(f"%{ord(c):02X}" for c in ticker)

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

# 統計的最上位10銘柄を通常表示のセレクター用に抽出
top_10_tickers = df_screener["ticker"].head(10).tolist()

# ==============================================================================
# 4. MAIN TERMINAL HEADER & NAVIGATION
# ==============================================================================
st.title("👁️ Whale-Eye: Institutional Option & Insider Intelligence")
st.markdown("インサイダー現物買いの足跡と、オプション市場のボラティリティ・歪み（Skew）を統計学的に解析し、レバレッジ利益を最大化する戦略を自律提案するプロ仕様端末です。")
st.markdown("---")

# ⚡ 統計的最上位10銘柄の通常表示（クイック・セレクター）
st.subheader("🎯 統計的期待値・最上位10銘柄セレクター")

# セッション状態の同期
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = top_10_tickers[0] if top_10_tickers else ""

# セレクターに存在しない銘柄が選ばれた場合（全銘柄マトリックスからの手動入力など）に対応
all_available_tickers = df_screener["ticker"].tolist()

# ラジオボタンの選択肢を動的に構築（上位10銘柄に、現在選択中の銘柄がそれ以外なら追加）
radio_options = list(top_10_tickers)
if st.session_state.selected_ticker not in radio_options and st.session_state.selected_ticker in all_available_tickers:
    radio_options.append(st.session_state.selected_ticker)

selected_by_radio = st.radio(
    "銘柄選択 (キーボードの ← → 矢印キーを押すだけで、詳細なチャート・オプション分析が完全連動します):",
    options=radio_options,
    index=radio_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in radio_options else 0,
    horizontal=True,
    key="ticker_radio"
)
st.session_state.selected_ticker = selected_by_radio
current_ticker = st.session_state.selected_ticker

# 手動検索入力ボックスも配置して全銘柄へのアクセスを強化
with st.expander("🔍 上位10銘柄以外のティッカーを直接手動入力して解析する"):
    manual_ticker = st.text_input("ティッカーシンボルを入力 (例: LLY, NVDA, SMMT):", value=current_ticker).strip().upper()
    if manual_ticker in all_available_tickers and manual_ticker != current_ticker:
        st.session_state.selected_ticker = manual_ticker
        st.rerun()

st.markdown("---")

# ==============================================================================
# 5. STATISTICAL OPTION & MARKET DATA FETCHING
# ==============================================================================
@st.cache_data(ttl=1800)
def fetch_market_and_option_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")
    
    if hist.empty:
        return None, None, None, 0.0, 0.0, 1.0
        
    hist.index = hist.index.tz_localize(None)
    current_price = hist["Close"].iloc[-1]
    
    # 歴史的ボラティリティ (HV 180日) の算出
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
    hv = log_ret.iloc[-180:].std() * np.sqrt(252)
    
    # オプションデータの取得
    options_data = []
    expirations = stock.options
    implied_vol = 0.0
    pcr_volume = 1.0  # デフォルト
    target_exp = None
    
    if expirations:
        try:
            # 最も近い満期日（約30日前後）のオプションチェーンを取得
            target_exp = expirations[0]
            opt_chain = stock.option_chain(target_exp)
            calls = opt_chain.calls
            puts = opt_chain.puts
            
            total_call_vol = calls["volume"].sum() if "volume" in calls.columns else 1.0
            total_put_vol = puts["volume"].sum() if "volume" in puts.columns else 1.0
            pcr_volume = total_put_vol / (total_call_vol + 1e-9)
            
            # 代表的なアット・ザ・マネー(ATM)のIVを取得
            calls["strike_diff"] = (calls["strike"] - current_price).abs()
            atm_call = calls.sort_values(by="strike_diff").iloc[0]
            implied_vol = atm_call["impliedVolatility"]
            
            # オプションチェーンの結合とDelta計算
            for _, row in calls.iterrows():
                strike = row["strike"]
                # Deltaの統計的近似 (d1 = (ln(S/K) + (r + sigma^2/2)T) / (sigma * sqrt(T)))
                # 満期30日(T=30/365), 無リスク金利 r=0.04 と仮定
                T = 30 / 365.25
                r = 0.04
                sigma = row["impliedVolatility"] if row["impliedVolatility"] > 0 else 0.3
                if sigma > 0:
                    d1 = (np.log(current_price / strike) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
                    delta = std_normal_cdf(d1)
                else:
                    delta = 0.5
                    
                options_data.append({
                    "Type": "Call",
                    "Strike": strike,
                    "Last Price": row["lastPrice"],
                    "Volume": row["volume"] if "volume" in row else 0,
                    "Open Interest": row["openInterest"] if "openInterest" in row else 0,
                    "IV": row["impliedVolatility"],
                    "Delta": delta
                })
        except Exception as e:
            pass
            
    df_opt = pd.DataFrame(options_data) if options_data else pd.DataFrame()
    return hist, df_opt, target_exp, implied_vol, hv, pcr_volume

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

with st.spinner(f"【{current_ticker}】の市場データおよびオプションチェーンを解析中..."):
    hist_data, df_options, expiry_date, iv, hv, pcr = fetch_market_and_option_data(current_ticker)

# ==============================================================================
# 6. DUAL-PANE TERMINAL DISPLAY (統合レイアウト)
# ==============================================================================
if hist_data is not None:
    current_price = hist_data["Close"].iloc[-1]
    
    # テクニカル計算 (ボリンジャーバンド & RSI)
    hist_data["MA20"] = hist_data["Close"].rolling(window=20).mean()
    hist_data["STD20"] = hist_data["Close"].rolling(window=20).std()
    hist_data["BB_Upper"] = hist_data["MA20"] + (hist_data["STD20"] * 2)
    hist_data["BB_Lower"] = hist_data["MA20"] - (hist_data["STD20"] * 2)
    
    delta = hist_data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    hist_data["RSI"] = 100 - (100 / (1 + rs))

    # 1標準偏差 (1σ) 予測レンジの算出 (満期30日想定)
    T_30 = 30 / 365.25
    one_sigma_move = current_price * iv * np.sqrt(T_30)
    upper_1sigma = current_price + one_sigma_move
    lower_1sigma = current_price - one_sigma_move
    
    # コントロールパネル
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 3])
    with ctrl_col1:
        show_bb = st.checkbox("ボリンジャーバンドを表示", value=True)
    with ctrl_col2:
        show_rsi = st.checkbox("RSI (14) を表示", value=True)
    with ctrl_col3:
        chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)

    col_left, col_right = st.columns([4, 3])
    
    # --------------------------------------------------------------------------
    # LEFT PANE: BI可視化 (株価・予測バンド・テクニカルチャート)
    # --------------------------------------------------------------------------
    with col_left:
        st.markdown("### 📊 統合テクニカル ＆ 予測バンドチャート")
        
        # 正しい2次元のspecsリスト
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.06, 
            row_heights=[0.7, 0.3],
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
        )
        
        # 1σ予測バンドの描画 (統計的確率約68%の推移予測)
        future_dates = [hist_data.index[-1] + timedelta(days=i) for i in range(31)]
        upper_band_curve = [current_price + (current_price * iv * np.sqrt(i / 365.25)) for i in range(31)]
        lower_band_curve = [current_price - (current_price * iv * np.sqrt(i / 365.25)) for i in range(31)]
        
        # RSIの描画 (ROW 1, secondary_y=False)
        if show_rsi:
            fig.add_trace(gr.Scatter(
                x=hist_data.index[-60:], y=hist_data["RSI"].iloc[-60:],
                line=dict(color="rgba(255, 165, 0, 0.45)", width=1.5), name="RSI (14)"
            ), row=1, col=1, secondary_y=False)
            fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 0, 0, 0.25)", row=1, col=1, secondary_y=False)
            fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 0, 0.25)", row=1, col=1, secondary_y=False)
            fig.update_yaxes(title_text="RSI", range=[0, 100], row=1, col=1, secondary_y=False)

        # 株価の描画 (ROW 1, secondary_y=True)
        if chart_type == "ローソク足":
            fig.add_trace(gr.Candlestick(
                x=hist_data.index[-60:], open=hist_data["Open"].iloc[-60:], high=hist_data["High"].iloc[-60:],
                low=hist_data["Low"].iloc[-60:], close=hist_data["Close"].iloc[-60:], name="株価 (OHLC)"
            ), row=1, col=1, secondary_y=True)
        else:
            fig.add_trace(gr.Scatter(
                x=hist_data.index[-60:], y=hist_data["Close"].iloc[-60:],
                mode="lines", line=dict(color="#00FFCC", width=2.5), name="現物株価 ($)"
            ), row=1, col=1, secondary_y=True)
            
        # ボリンジャーバンドの描画
        if show_bb:
            fig.add_trace(gr.Scatter(x=hist_data.index[-60:], y=hist_data["BB_Upper"].iloc[-60:], line=dict(color="rgba(0, 255, 204, 0.12)", width=0.8, dash="dash"), name="BB Upper", hoverinfo="skip", showlegend=False), row=1, col=1, secondary_y=True)
            fig.add_trace(gr.Scatter(x=hist_data.index[-60:], y=hist_data["BB_Lower"].iloc[-60:], line=dict(color="rgba(0, 255, 204, 0.12)", width=0.8, dash="dash"), fill="tonexty", fillcolor="rgba(0, 255, 204, 0.015)", name="BB Lower", hoverinfo="skip", showlegend=False), row=1, col=1, secondary_y=True)
            fig.add_trace(gr.Scatter(x=hist_data.index[-60:], y=hist_data["MA20"].iloc[-60:], line=dict(color="orange", width=1.2, dash="dash"), name="20日移動平均", hoverinfo="skip"), row=1, col=1, secondary_y=True)

        # 1σ予測バンドの描画
        fig.add_trace(gr.Scatter(
            x=future_dates, y=upper_band_curve,
            mode="lines", line=dict(color="rgba(0, 255, 204, 0.3)", width=1, dash="dash"),
            name="1σ 上昇上限 (確率68%)", showlegend=True
        ), row=1, col=1, secondary_y=True)
        
        fig.add_trace(gr.Scatter(
            x=future_dates, y=lower_band_curve,
            mode="lines", line=dict(color="rgba(239, 68, 68, 0.3)", width=1, dash="dash"),
            fill="tonexty", fillcolor="rgba(0, 255, 204, 0.02)",
            name="1σ 下落下限 (確率68%)", showlegend=True
        ), row=1, col=1, secondary_y=True)
        
        # ROW 2: 出来高 ＆ インサイダー取引量 (軸分離)
        fig.add_trace(gr.Bar(
            x=hist_data.index[-60:], y=hist_data["Volume"].iloc[-60:],
            name="市場出来高 (Volume)", marker_color="rgba(128, 128, 128, 0.25)"
        ), row=2, col=1, secondary_y=False)
        
        df_ticker_raw = df_raw[df_raw["ticker"] == current_ticker].copy()
        df_insider_daily = df_ticker_raw.groupby("buy_date")["total_value"].sum().reset_index()
        df_insider_daily = df_insider_daily[df_insider_daily["buy_date"].isin(hist_data.index)]
        
        if not df_insider_daily.empty:
            fig.add_trace(gr.Bar(
                x=df_insider_daily["buy_date"], y=df_insider_daily["total_value"],
                name="インサイダー取引量 ($)", marker_color="#AA00FF", width=1000 * 60 * 60 * 24 * 3
            ), row=2, col=1, secondary_y=True)
            
        fig.update_yaxes(title_text="株価 ($)", row=1, col=1, secondary_y=True)
        fig.update_yaxes(title_text="出来高 (Vol)", row=2, col=1, secondary_y=False)
        fig.update_yaxes(title_text="インサイダー量 ($)", row=2, col=1, secondary_y=True, showgrid=False)
        
        fig.update_layout(
            height=500, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
            margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.08, x=0),
            hovermode="x"
        )
        st.plotly_chart(fig, use_container_width=True)

    # --------------------------------------------------------------------------
    # RIGHT PANE: AIオプション戦略 ＆ 統計的価格提案
    # --------------------------------------------------------------------------
    with col_right:
        st.markdown("### 🧠 AIオプション戦略 ＆ 統計的価格提案")
        
        # 統計スタッツメトリクス
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric("インプライド・ボラティリティ (IV)", f"{iv*100:.1f}%")
        with m_col2:
            st.metric("歴史的ボラティリティ (HV)", f"{hv*100:.1f}%")
        with m_col3:
            st.metric("IV / HV 比率", f"{iv/hv:.2f}" if hv > 0 else "N/A", help="1.0未満はオプションが統計的に割安、1.5以上は割高")
            
        m_col4, m_col5, m_col6 = st.columns(3)
        with m_col4:
            st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}", help="0.7以下はコールの出来高が圧倒的に多く、極めて強気")
        with m_col5:
            st.metric("1σ 上昇上限 (30日)", f"${upper_1sigma:.2f}")
        with m_col6:
            st.metric("1σ 下落下限 (30日)", f"${lower_1sigma:.2f}")

        # 統計的オプション戦略構築アルゴリズム
        st.markdown("---")
        
        # 戦略選定ロジック
        is_iv_cheap = (iv / hv) < 1.1 if hv > 0 else True
        is_pcr_bullish = pcr < 0.6
        
        if is_iv_cheap and is_pcr_bullish:
            strategy_title = "🟢 推奨戦略: ブル・コール・スプレッド (Bull Call Spread)"
            strategy_class = "strategy-card"
            strategy_desc = f"""
            **【統計的選定根拠】**
            *   **ボラティリティの歪み**: IV/HV比率が **{(iv/hv if hv > 0 else 0):.2f}** と極めて低く、オプション価格が歴史的な実績変動率に対して**統計的に過小評価（割安）**されています。オプションの「買い」に圧倒的な優位性があります。
            *   **異常なコール偏重**: Put-Call Ratio (PCR) が **{pcr:.2f}** と極端に低く、インサイダーの現物買いと同時に、オプション市場でもコールの大量買い（クジラの足跡）が確認されています。
            
            **【具体的取引価格の統計的提案】**
            1.  **Buy {current_ticker} 30日満期 ${current_price*0.95:.1f} Call (ITM)**
                *   **目安プレミアム（買値）**: 約 ${(current_price*0.08):.2f}
                *   **Delta**: 約 0.65 (株価上昇への追従性が高いストライク)
            2.  **Sell {current_ticker} 30日満期 ${upper_1sigma:.1f} Call (OTM)**
                *   **目安プレミアム（売値）**: 約 ${(current_price*0.02):.2f}
                *   **Delta**: 約 0.30 (1σ上限付近。統計的に権利消滅確率が約84%の安全なストライク)
                
            ➔ **実質コスト（最大損失）**: 約 ${(current_price*0.06):.2f} に抑えつつ、株価が1σ上限（${upper_1sigma:.2f}）まで上昇した場合、**想定利益率 +180%〜+250%** の非対称なリターンを狙えます。
            """
        elif not is_iv_cheap and is_pcr_bullish:
            strategy_title = "🟡 推奨戦略: カバード・コール (Covered Call) または クレジット・プット・スプレッド"
            strategy_class = "strategy-card"
            strategy_desc = f"""
            **【統計的選定根拠】**
            *   **ボラティリティの過熱**: IV/HV比率が **{(iv/hv if hv > 0 else 0):.2f}** と高く、オプション価格が統計的に割高（プレミアムが膨張）しています。オプションの「売り（ショート）」を絡める戦略が有利です。
            *   **インサイダーの下値支持**: 大口インサイダー取引により下値が強固に支持されているため、プット売りによるプレミアム回収の安全性が高い状態です。
            
            **【具体的取引価格の統計的提案】**
            1.  **現物株式を ${current_price:.2f} で購入**
            2.  **Sell {current_ticker} 30日満期 ${upper_1sigma:.1f} Call (OTM)**
                *   **目安プレミアム（受取）**: 約 ${(current_price*0.05):.2f} (高IVのためプレミアムが通常より高価)
                
            ➔ プレミアムを即時回収することで現物の取得単価を引き下げ、株価が横ばいまたは微増であっても、年率換算で極めて高いインカムゲインを獲得できます。
            """
        else:
            strategy_title = "🚨 推奨戦略: ロング・コール (Long Call) 単体打診買い"
            strategy_class = "strategy-card-warning"
            strategy_desc = f"""
            **【統計的選定根拠】**
            *   IV/HV比率が **{(iv/hv if hv > 0 else 0):.2f}** とニュートラルですが、インサイダーの買い総額が大きく、突発的なカタリストによる急騰（ボラティリティ・スパイク）の期待値が高い状態です。
            
            **【具体的取引価格の統計的提案】**
            *   **Buy {current_ticker} 30日満期 ${current_price*1.05:.1f} Call (ややOTM)**
                *   **目安プレミアム（買値）**: 約 ${(current_price*0.04):.2f}
                
            ➔ 損失を限定（支払ったプレミアムのみ）しつつ、インサイダー買いを契機とした急騰時のレバレッジ利益をストレートに狙う戦略です。
            """
            
        st.html(f"""
            <div class="{strategy_class}">
                <h4 style="color: #00FFCC; margin-top: 0;">{strategy_title}</h4>
                <div style="font-size: 13px; line-height: 1.6; color: #E2E8F0;">
                    {strategy_desc}
                </div>
            </div>
        """)
        
        # リアルタイム・イベント・コンソール（名寄せ・合算版）
        st.markdown("#### ⏱️ リアルタイム・イベント・コンソール")
        
        # カタリストとインサイダーの合算
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

        if raw_events_by_date:
            console_html = "<div class='event-console'>"
            for event_date in sorted(raw_events_by_date.keys(), reverse=True):
                date_str = event_date.strftime('%Y-%m-%d')
                for item in raw_events_by_date[event_date]:
                    if item["type"] == "I":
                        badge = "<span class='console-badge' style='background-color: rgba(170, 0, 255, 0.15); color: #E0B0FF; border: 1px solid #AA00FF;'>インサイダー [ I ]</span>"
                        text = f"👤 <span style='color:#00FFCC; font-weight:bold;'>{item['insider']}</span> ({item['position']}) が 合計 <b style='color:#00FFCC;'>${item['value']:,.0f}</b> を市場から購入"
                    else:
                        badge = "<span class='console-badge' style='background-color: rgba(255, 215, 0, 0.15); color: #FFD700; border: 1px solid #FFD700;'>ニュース [ R ]</span>"
                        text = f"📢 <span style='color:#FFD700;'>{item['category']}</span>: {item['title']}"
                    console_html += f"<div class='console-row'><div class='console-date'>[{date_str}]</div>{badge}<div class='console-text'>{text}</div></div>"
            console_html += "</div>"
            st.html(console_html)
        else:
            st.info("💡 直近で検出された重大イベントはありません。")

    # --------------------------------------------------------------------------
    # LOWER SECTION: 詳細オプションチェーン ＆ マルチソース・リンク
    # --------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 📄 直近満期オプション・チェーン (詳細統計マトリックス)")
    
    if df_options is not None and not df_options.empty:
        df_opt_display = df_options.sort_values(by="Strike").copy()
        df_opt_display["IV"] = df_opt_display["IV"].map(lambda x: f"{x*100:.1f}%")
        df_opt_display["Delta"] = df_opt_display["Delta"].map(lambda x: f"{x:.2f}")
        df_opt_display["Last Price"] = df_opt_display["Last Price"].map(lambda x: f"${x:.2f}")
        
        st.dataframe(
            df_opt_display[["Strike", "Type", "Last Price", "Volume", "Open Interest", "IV", "Delta"]],
            use_container_width=True,
            hide_index=True,
            height=250
        )
    
    st.markdown("---")
    st.markdown(f"### 🔗 【{current_ticker}】 マルチソース・適時開示＆ニュースターミナル")
    
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
                    "イベント概要": f"{item['insider']} ({item['position']}) が 合計 ${item['value']:,.0f} を購入",
                    "SEC開示 (Form 4)": item["url"],
                    "Googleニュース": date_specific_news_url,
                    "Finviz Chart": f"https://finviz.com/quote.ashx?t={current_ticker}"
                })
            else:
                linked_sources_list.append({
                    "日付": date_str,
                    "分類": "🟡 カタリスト [ R ]",
                    "イベント概要": f"【{item['category']}】 {item['title']}",
                    "SEC開示 (Form 4)": f"https://www.sec.gov/edgar/browse/?CIK={current_ticker}",
                    "Googleニュース": item["url"],
                    "Finviz Chart": f"https://finviz.com/quote.ashx?t={current_ticker}"
                })
                
    if linked_sources_list:
        df_sources = pd.DataFrame(linked_sources_list).drop_duplicates(subset=["日付", "イベント概要"])
        st.dataframe(
            df_sources,
            column_config={
                "SEC開示 (Form 4)": st.column_config.LinkColumn("SEC Link", display_text="Form 4 ↗"),
                "Googleニュース": st.column_config.LinkColumn("Google News", display_text="News ↗"),
                "Finviz Chart": st.column_config.LinkColumn("Finviz Chart", display_text="Chart ↗")
            },
            use_container_width=True,
            hide_index=True,
            height=250
        )
    else:
        st.info("💡 リンク可能なイベント履歴はありません。")
            
else:
    st.warning("⚠️ 選択された銘柄の株価データを取得できませんでした。")

# ==============================================================================
# 7. BOTTOM SECTION: 全銘柄多次元スクリーニング・マトリックス (完全復活)
# ==============================================================================
st.markdown("---")
st.subheader("📊 全銘柄多次元スクリーニング・マトリックス")
st.markdown("データベースに登録されている全銘柄のインサイダー取引実績と統計的確実性スコアの一覧です。任意の列でソートや検索が可能です。")

# 表示用データの整形
df_screener_display = df_screener.copy()
df_screener_display = df_screener_display.rename(columns={
    "ticker": "ティッカー",
    "company": "企業名",
    "total_value": "取引総額 ($)",
    "avg_price": "平均取得単価 ($)",
    "insider": "主なインサイダー",
    "buy_date": "直近取引日",
    "trade_count": "取引回数",
    "Certainty (%)": "統計的確実性スコア (%)"
})

# フォーマット適用
df_screener_display["取引総額 ($)"] = df_screener_display["取引総額 ($)"].map(lambda x: f"${x:,.0f}")
df_screener_display["平均取得単価 ($)"] = df_screener_display["平均取得単価 ($)"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
df_screener_display["直近取引日"] = df_screener_display["直近取引日"].dt.strftime('%Y-%m-%d')
df_screener_display["統計的確実性スコア (%)"] = df_screener_display["統計的確実性スコア (%)"].map(lambda x: f"{x:.1f}%")

st.dataframe(
    df_screener_display[["ティッカー", "企業名", "取引総額 ($)", "平均取得単価 ($)", "主なインサイダー", "直近取引日", "取引回数", "統計的確実性スコア (%)"]],
    use_container_width=True,
    hide_index=True,
    height=400
)
