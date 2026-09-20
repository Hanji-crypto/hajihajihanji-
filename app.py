import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as gr
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import yfinance as yf

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Multi-Factor AI Screener & Chart Terminal",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# カスタムCSS
st.markdown("""
    <style>
    .stApp {
        background-color: #0E1117;
        color: #E0E0E0;
    }
    div[data-testid="stMetricValue"] {
        font-size: 20px;
        font-weight: bold;
        color: #00FFCC !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #888888 !important;
    }
    .reportview-container .main .block-container {
        padding-top: 1rem;
    }
    hr {
        border-color: #262730 !important;
    }
    a {
        color: #00FFCC !important;
        text-decoration: none;
        font-weight: bold;
    }
    a:hover {
        text-decoration: underline;
    }
    /* AI考察カードのスタイル */
    .ai-box {
        background-color: #1E293B;
        border-left: 5px solid #00FFCC;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    .ai-box-warning {
        background-color: #3B1E1E;
        border-left: 5px solid #FF4444;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

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
        SELECT 
            filing_date,
            insider,
            position,
            ticker,
            company,
            avg_price,
            buy_date,
            total_shares as shares,
            total_value,
            filing_url,
            {sector_select}
        FROM insider_trades
        WHERE ticker IS NOT NULL 
          AND ticker != '' 
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce')
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors='coerce')
    df["shares"] = pd.to_numeric(df["shares"], errors='coerce')
    
    # クレンジング
    df["ticker"] = df["ticker"].str.strip().str.upper()
    exclude_words = {
        "NONE", "N/A", "NA", "NULL", "DIRECTOR", "OFFICER", "PRESIDENT", 
        "CEO", "CFO", "TRUST", "COMMON", "STOCK", "SHARES", "BENEFICIAL"
    }
    df = df[~df["ticker"].isin(exclude_words)]
    df = df[df["ticker"].str.match(r'^[A-Z0-9\.\-]{1,5}$', na=False)]
    df = df[df["total_value"] < 500000000]

    # セクター補完
    def map_sector(row):
        ticker = row["ticker"]
        db_sector = row["sector"]
        if pd.notna(db_sector) and db_sector not in ["Other", "", "N/A", "None"]:
            return db_sector
            
        healthcare_tickers = {"CYBN", "ARTV", "ZSTK", "LLY", "MRNA", "PFE", "BIIB", "GILD"}
        financial_tickers = {"ARDC", "ARES", "GS", "MS", "JPM", "BAC", "C", "WFC"}
        tech_tickers = {"AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA"}
        industrial_tickers = {"WAST", "CAT", "GE", "HON", "MMM", "UNP", "RS", "GWAV"}
        
        if ticker in healthcare_tickers:
            return "Healthcare"
        elif ticker in financial_tickers:
            return "Financials"
        elif ticker in tech_tickers:
            return "Technology"
        elif ticker in industrial_tickers:
            return "Industrials"
            
        company_lower = str(row["company"]).lower()
        if any(x in company_lower for x in ["biotherapeutics", "pharma", "therapeutics", "biosciences", "health", "medical", "cancer"]):
            return "Healthcare"
        if any(x in company_lower for x in ["fund", "capital", "acquisition", "credit", "bancorp", "bank", "insurance"]):
            return "Financials"
        if any(x in company_lower for x in ["tech", "software", "digital", "systems"]):
            return "Technology"
        if any(x in company_lower for x in ["service", "waste", "industries", "energy", "resource"]):
            return "Industrials"
            
        return "Other"

    df["sector"] = df.apply(map_sector, axis=1)
    return df

try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"SQLiteデータベースの読み込みに失敗しました。: {e}")
    st.stop()

# ==============================================================================
# 3. COGNITIVE ENGINE (マルチファクター・レーティング)
# ==============================================================================
def generate_screener(df):
    three_months_ago = datetime.now() - timedelta(days=90)
    df_recent = df[df["buy_date"] >= three_months_ago]
    
    if df_recent.empty:
        df_recent = df
        
    summary = df_recent.groupby("ticker").agg({
        "total_value": "sum",
        "avg_price": "mean",
        "insider": lambda x: ", ".join(x.unique()[:2]),
        "company": "first",
        "buy_date": "max",
        "sector": "first",
        "ticker": "count",
        "shares": "sum"
    }).rename(columns={"ticker": "trade_count"}).reset_index()
    
    def calculate_advanced_metrics(row):
        ticker = row["ticker"]
        sector = row["sector"]
        avg_price = row["avg_price"]
        val = row["total_value"]
        
        financial_health = 70.0  
        valuation_score = 50.0   
        speculative_index = 30.0 
        
        if avg_price < 2.0:
            financial_health = max(10.0, 30.0 - (1.0 / (avg_price + 0.1)) * 5)
            valuation_score = 85.0   
            speculative_index = 95.0  
        elif sector == 'Technology':
            financial_health = min(95.0, 75.0 + (np.log10(val + 1) * 2))
            valuation_score = max(30.0, 85.0 - (avg_price / 15.0))
            speculative_index = 25.0
        elif sector == 'Healthcare':
            financial_health = 60.0
            valuation_score = 55.0
            speculative_index = 65.0  
        elif sector in ['Financials', 'Industrials', 'Energy']:
            financial_health = 75.0
            valuation_score = 70.0   
            speculative_index = 35.0
        else:
            financial_health = 68.0
            valuation_score = 60.0
            speculative_index = 45.0
            
        if ticker in ["ZSTK", "ZeroStack"]:
            financial_health = 25.0
            speculative_index = 98.0
            
        size_score = min(100.0, 40.0 + (np.log10(val + 1) * 8.5))
        multi_factor_certainty = (0.4 * size_score) + (0.4 * financial_health) - (0.2 * speculative_index)
        multi_factor_certainty = min(98.5, max(10.0, multi_factor_certainty))
        
        return pd.Series([financial_health, valuation_score, speculative_index, multi_factor_certainty])

    summary[['Financial Health', 'Valuation Score', 'Speculative Index', 'Certainty (%)']] = summary.apply(calculate_advanced_metrics, axis=1)
    
    def get_ai_status(row):
        score = row["Certainty (%)"]
        spec = row["Speculative Index"]
        
        if spec >= 85:
            return "🚨 投機的警戒 (High Risk Speculative)"
        elif score >= 75:
            return "🔥 強気 (Strong Buy)"
        elif score >= 60:
            return "🟢 押し目推奨 (Accumulate)"
        else:
            return "🟡 様子見 (Hold/Watch)"
            
    def get_ai_analysis(row):
        score = row["Certainty (%)"]
        val = row["total_value"]
        insiders = row["insider"]
        avg_p = row["avg_price"]
        spec = row["Speculative Index"]
        
        if spec >= 85:
            return f"【投機的リスク極大】インサイダー買い（${val:,.0f}）が検出されましたが、株価水準（${avg_p:,.2f}）や財務健全性スコアが極めて低く、希薄化や破産リスクが隣り合わせです。専門家としては「投機枠」としての厳重な監視を推奨します。"
        
        if score >= 75:
            return f"【優良シグナル】財務健全性が高く、インサイダー（{insiders}）が直近で総額 ${val:,.0f}（平均単価: ${avg_p:,.2f}）の大規模な買いを実行。中長期の底値圏である確実性が非常に高いです。"
        elif score >= 60:
            return f"【好材料】内部関係者による総額 ${val:,.0f} のまとまった買い。下値支持線として機能する可能性が高く、押し目買いに適した水準です。"
        else:
            return f"【様子見】直近で ${val:,.0f} 規模のインサイダー買いが確認されました。財務スコアや取引規模を鑑み、追加の買い増しやテクニカルの反発を待ちたい局面です。"

    summary["AI Status"] = summary.apply(get_ai_status, axis=1)
    summary["AI Analysis (投資考察)"] = summary.apply(get_ai_analysis, axis=1)
    
    summary["Finviz Chart"] = summary["ticker"].apply(lambda t: f"https://finviz.com/quote.ashx?t={t}")
    summary["Yahoo Finance"] = summary["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    summary["SEC EDGAR"] = summary["ticker"].apply(lambda t: f"https://www.sec.gov/edgar/browse/?CIK={t}")
    
    summary = summary.sort_values(by="Certainty (%)", ascending=False)
    return summary

df_screener = generate_screener(df_raw)

# ==============================================================================
# 4. DASHBOARD DISPLAY
# ==============================================================================
st.title("👁️ Whale-Eye: Multi-Factor AI Screener")
st.markdown("大口インサイダー取引データから、**「財務健全性」「バリュエーション割安度」「投機性」**をセクター特性に合致させてレーティングした多要素スクリーナーです。")
st.markdown("---")

# ------------------------------------------------------------------------------
# A. SECTOR SLICER (セクター・スライサー)
# ------------------------------------------------------------------------------
st.subheader("🔍 セクター・スライサー")
all_sectors = sorted(df_screener["sector"].unique().tolist())
selected_sectors = st.multiselect(
    "セクター選択:",
    options=all_sectors,
    default=all_sectors,
    label_visibility="collapsed"
)
df_filtered_screener = df_screener[df_screener["sector"].isin(selected_sectors)]

st.markdown("---")

# ------------------------------------------------------------------------------
# B. MAIN SCREENER TABLE (複数選択対応)
# ------------------------------------------------------------------------------
st.subheader("📋 マルチファクター・高密度銘柄マトリックス")
st.info("💡 **【複数選択ガイド】** Windowsは `Ctrl` キー、Macは `Cmd` キーを押しながら行をクリックすると、**複数銘柄を選択して下部チャートで相対パフォーマンスを重ね合わせ比較**できます。")

# 表示用にデータフレームを整形
df_display = df_filtered_screener.copy()
df_display["Certainty (%)"] = df_display["Certainty (%)"].map(lambda x: f"{x:.1f}%")
df_display["Financial Health"] = df_display["Financial Health"].map(lambda x: f"{x:.1f}/100")
df_display["Valuation Score"] = df_display["Valuation Score"].map(lambda x: f"{x:.1f}/100")
df_display["Speculative Index"] = df_display["Speculative Index"].map(lambda x: f"{x:.1f}/100")
df_display["Total Buy Value"] = df_display["total_value"].map(lambda x: f"${x:,.0f}")
df_display["Avg Buy Price"] = df_display["avg_price"].map(lambda x: f"${x:,.2f}")
df_display["Last Trade Date"] = df_display["buy_date"].dt.strftime('%Y-%m-%d')

df_display = df_display[[
    "ticker", 
    "company", 
    "Finviz Chart",
    "AI Status", 
    "Certainty (%)", 
    "Financial Health",
    "Valuation Score",
    "Speculative Index",
    "Total Buy Value", 
    "Avg Buy Price", 
    "Last Trade Date",
    "sector",
    "SEC EDGAR",
    "Yahoo Finance"
]]

df_display.columns = [
    "Ticker", 
    "企業名", 
    "Finviz Chart",
    "AI投資判断", 
    "AI確実性", 
    "財務健全性",
    "割安度スコア",
    "投機性インデックス",
    "直近買い総額", 
    "平均取得単価", 
    "最終取引日",
    "セクター",
    "SEC EDGAR",
    "Yahoo Finance"
]

event = st.dataframe(
    df_display,
    column_config={
        "Finviz Chart": st.column_config.LinkColumn("📊 Finviz Chart", display_text="Chart ↗"),
        "SEC EDGAR": st.column_config.LinkColumn("📄 SEC適時開示", display_text="View Filings ↗"),
        "Yahoo Finance": st.column_config.LinkColumn("📰 Detail (Yahoo)", display_text="View Detail ↗")
    },
    use_container_width=True,
    hide_index=True,
    height=300,
    on_select="rerun", 
    selection_mode="multi-row"
)

# 選択されたすべての行のインデックスを取得
selected_tickers = []
if event and "rows" in event.get("selection", {}):
    selected_rows = event["selection"]["rows"]
    if selected_rows:
        selected_tickers = [df_display.iloc[r]["Ticker"] for r in selected_rows]

# 選択がない場合は、デフォルトでテーブルの1行目を選択状態にする
if not selected_tickers and not df_display.empty:
    selected_tickers = [df_display.iloc[0]["Ticker"]]

st.markdown("---")

# ==============================================================================
# 5. DYNAMIC ANALYTICS TERMINAL (複数銘柄のAI考察タブ化 ＆ 取引履歴)
# ==============================================================================
if selected_tickers:
    st.subheader(f"📊 選択銘柄分析ターミナル ({', '.join(selected_tickers)})")
    
    col_ai, col_feed = st.columns([1, 1])
    
    with col_ai:
        st.markdown("#### 👁️ AI投資考察 ＆ スタッツ")
        
        if len(selected_tickers) > 1:
            tabs = st.tabs([f"👁️ {t}" for t in selected_tickers])
            for i, t in enumerate(selected_tickers):
                with tabs[i]:
                    data = df_filtered_screener[df_filtered_screener["ticker"] == t].iloc[0]
                    is_warning = "🚨" in data["AI Status"]
                    box_class = "ai-box-warning" if is_warning else "ai-box"
                    st.markdown(f"""
                        <div class="{box_class}">
                            <h5>{data['AI Status']} ({t})</h5>
                            <p style="font-size: 14px; line-height: 1.5; margin-bottom: 5px;">{data['AI Analysis (投資考察)']}</p>
                            <small style="color: #888888;">
                                財務: {data['Financial Health']:.1f}/100 | 割安: {data['Valuation Score']:.1f}/100 | 投機: {data['Speculative Index']:.1f}/100
                            </small>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    m_col1, m_col2 = st.columns(2)
                    with m_col1:
                        st.metric("累計購入総額", f"${data['total_value']:,.0f}")
                        st.metric("総取得株数", f"{data['shares']:,.0f} 株")
                    with m_col2:
                        st.metric("累計取引件数", f"{data['trade_count']} 件")
                        st.metric("平均取得単価", f"${data['avg_price']:,.2f}")
        else:
            t = selected_tickers[0]
            data = df_filtered_screener[df_filtered_screener["ticker"] == t].iloc[0]
            is_warning = "🚨" in data["AI Status"]
            box_class = "ai-box-warning" if is_warning else "ai-box"
            st.markdown(f"""
                <div class="{box_class}">
                    <h5>{data['AI Status']} ({t})</h5>
                    <p style="font-size: 14px; line-height: 1.5; margin-bottom: 5px;">{data['AI Analysis (投資考察)']}</p>
                    <small style="color: #888888;">
                        財務: {data['Financial Health']:.1f}/100 | 割安: {data['Valuation Score']:.1f}/100 | 投機: {data['Speculative Index']:.1f}/100
                    </small>
                </div>
            """, unsafe_allow_html=True)
            
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.metric("累計購入総額", f"${data['total_value']:,.0f}")
                st.metric("総取得株数", f"{data['shares']:,.0f} 株")
            with m_col2:
                st.metric("累計取引件数", f"{data['trade_count']} 件")
                st.metric("平均取得単価", f"${data['avg_price']:,.2f}")

    with col_feed:
        st.markdown("#### ⏱️ Recent Raw Insider Feed (直近の取引履歴)")
        df_filtered_raw = df_raw[df_raw["ticker"].isin(selected_tickers)]
        
        df_raw_display = df_filtered_raw.sort_values(by="filing_date", ascending=False).head(10).copy()
        df_raw_display["filing_date"] = df_raw_display["filing_date"].dt.strftime('%Y-%m-%d')
        df_raw_display["buy_date"] = df_raw_display["buy_date"].dt.strftime('%Y-%m-%d')
        df_raw_display["total_value"] = df_raw_display["total_value"].map(lambda x: f"${x:,.0f}")
        df_raw_display["avg_price"] = df_raw_display["avg_price"].map(lambda x: f"${x:,.2f}")
        df_raw_display["shares"] = df_raw_display["shares"].map(lambda x: f"{x:,.0f}")

        st.dataframe(
            df_raw_display[["filing_date", "ticker", "insider", "position", "avg_price", "total_value", "filing_url"]],
            column_config={
                "filing_url": st.column_config.LinkColumn("SEC Link", display_text="Form 4 ↗")
            },
            use_container_width=True,
            hide_index=True,
            height=250
        )

    st.markdown("---")

    # ==============================================================================
    # 6. MULTI-LAYOUT & MULTI-ASSET CHART SYSTEM (動的コントロール切り替え)
    # ==============================================================================
    st.markdown("### 📈 インサイダー買い・テクニカルチャート / 複数銘柄パフォーマンス比較")
    
    is_comparison_mode = len(selected_tickers) > 1
    
    # ⚡ 【動的コントロールパネル】
    # 複数選択時と単一選択時で、上部の設定項目自体を完全に切り替える
    if is_comparison_mode:
        # 複数選択時のコントロール
        ctrl_col1, ctrl_col2 = st.columns([2, 5])
        with ctrl_col1:
            chart_layout_mode = st.selectbox(
                "📊 比較モード", 
                options=["相対パフォーマンス比較 (%)", "個別絶対価格重ね書き ($)"], 
                index=0
            )
        # 複数選択時はBBやRSI、ローソク足オプションは非表示（画面をすっきりさせる）
        show_bb = False
        show_rsi = False
        chart_type = "折れ線"
    else:
        # 単一選択時のコントロール（すべてのオプションが有効）
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([2, 2, 2, 2])
        with ctrl_col1:
            chart_layout_mode = st.selectbox(
                "📊 チャート配置モード", 
                options=["縦分割 (Vertical)", "横分割 (Horizontal)", "重複 (Overlay)"], 
                index=0
            )
        with ctrl_col2:
            show_bb = st.checkbox("ボリンジャーバンドを表示", value=True)
        with ctrl_col3:
            show_rsi = st.checkbox("RSI (14) を表示", value=True)
        with ctrl_col4:
            chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)

    # yfinanceから安全に複数株価を取得
    @st.cache_data(ttl=3600)
    def fetch_multiple_stock_prices(tickers):
        data_dict = {}
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                hist = stock.history(period="1y")
                if not hist.empty:
                    hist.index = hist.index.tz_localize(None)
                    data_dict[t] = hist
            except Exception as e:
                pass
        return data_dict

    with st.spinner("株価データを取得中..."):
        df_prices_map = fetch_multiple_stock_prices(selected_tickers)

    # --- CHART GENERATION LOGIC ---
    if df_prices_map:
        if is_comparison_mode:
            # ==========================================
            # 複数銘柄比較チャート（ボリンジャーバンド等は非表示）
            # ==========================================
            fig = gr.Figure()
            
            for t, df_prices in df_prices_map.items():
                if df_prices.empty:
                    continue
                
                if "相対パフォーマンス比較 (%)" in chart_layout_mode:
                    base_price = df_prices["Close"].iloc[0]
                    relative_perf = ((df_prices["Close"] - base_price) / base_price) * 100
                    
                    fig.add_trace(gr.Scatter(
                        x=df_prices.index,
                        y=relative_perf,
                        mode="lines",
                        name=f"{t} 相対推移 (%)",
                        line=dict(width=2)
                    ))
                    y_axis_title = "相対パフォーマンス (%)"
                else:
                    fig.add_trace(gr.Scatter(
                        x=df_prices.index,
                        y=df_prices["Close"],
                        mode="lines",
                        name=f"{t} 株価 ($)",
                        line=dict(width=2)
                    ))
                    y_axis_title = "株価 ($)"

            fig.update_layout(
                height=500,
                template="plotly_dark",
                paper_bgcolor="#0E1117",
                plot_bgcolor="#0E1117",
                yaxis_title=y_axis_title,
                xaxis_title="日付",
                margin=dict(l=20, r=20, t=20, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            # ==========================================
            # 単一銘柄テクニカルチャート（ボリンジャーバンド、RSI、ローソク足が完全に機能）
            # ==========================================
            t = selected_tickers[0]
            df_prices = df_prices_map[t]
            
            # テクニカル指標の計算
            df_prices["MA20"] = df_prices["Close"].rolling(window=20).mean()
            df_prices["STD20"] = df_prices["Close"].rolling(window=20).std()
            df_prices["BB_Upper"] = df_prices["MA20"] + (df_prices["STD20"] * 2)
            df_prices["BB_Lower"] = df_prices["MA20"] - (df_prices["STD20"] * 2)
            
            delta = df_prices["Close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-9)
            df_prices["RSI"] = 100 - (100 / (1 + rs))
            
            df_ticker_raw = df_raw[df_raw["ticker"] == t].copy()
            insider_markers = []
            for _, trade in df_ticker_raw.iterrows():
                trade_date = trade["buy_date"]
                closest_date_idx = df_prices.index.get_indexer([trade_date], method="nearest")[0]
                closest_date = df_prices.index[closest_date_idx]
                plot_price = df_prices.loc[closest_date, "Low"] * 0.98
                
                insider_markers.append(dict(
                    date=closest_date,
                    price=plot_price,
                    insider=trade["insider"],
                    value=trade["total_value"]
                ))
            df_markers = pd.DataFrame(insider_markers) if insider_markers else pd.DataFrame()

            if "縦分割" in chart_layout_mode:
                if show_rsi:
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])
                else:
                    fig = make_subplots(rows=1, cols=1)
                
                if chart_type == "ローソク足":
                    fig.add_trace(gr.Candlestick(x=df_prices.index, open=df_prices["Open"], high=df_prices["High"], low=df_prices["Low"], close=df_prices["Close"], name="株価 (OHLC)"), row=1, col=1)
                else:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["Close"], mode="lines", line=dict(color="#00FFCC", width=2), name="終値"), row=1, col=1)
                
                if show_bb:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.2)", width=1, dash="dash"), name="BB Upper", showlegend=False), row=1, col=1)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.2)", width=1, dash="dash"), fill="tonexty", fillcolor="rgba(0, 255, 204, 0.03)", name="BB Lower", showlegend=False), row=1, col=1)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["MA20"], line=dict(color="orange", width=1.5, dash="dash"), name="20日移動平均"), row=1, col=1)
                
                if not df_markers.empty:
                    fig.add_trace(gr.Scatter(x=df_markers["date"], y=df_markers["price"], mode="markers", marker=dict(symbol="triangle-up", size=16, color="#E0B0FF", line=dict(color="#AA00FF", width=2)), text=df_markers.apply(lambda r: f"{r['insider']}<br>購入額: ${r['value']:,.0f}", axis=1), hoverinfo="text+x+y", name="インサイダー買い"), row=1, col=1)
                
                if show_rsi:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["RSI"], line=dict(color="orange", width=1.5), name="RSI (14)"), row=2, col=1)
                    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1, opacity=0.5)
                    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1, opacity=0.5)
                
                fig.update_layout(height=600, template="plotly_dark", paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig, use_container_width=True)

            elif "横分割" in chart_layout_mode:
                if show_rsi:
                    fig = make_subplots(rows=1, cols=2, shared_yaxes=False, horizontal_spacing=0.08, column_widths=[0.7, 0.3])
                else:
                    fig = make_subplots(rows=1, cols=1)
                
                if chart_type == "ローソク足":
                    fig.add_trace(gr.Candlestick(x=df_prices.index, open=df_prices["Open"], high=df_prices["High"], low=df_prices["Low"], close=df_prices["Close"], name="株価 (OHLC)"), row=1, col=1)
                else:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["Close"], mode="lines", line=dict(color="#00FFCC", width=2), name="終値"), row=1, col=1)
                
                if show_bb:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.2)", width=1, dash="dash"), name="BB Upper", showlegend=False), row=1, col=1)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.2)", width=1, dash="dash"), fill="tonexty", fillcolor="rgba(0, 255, 204, 0.03)", name="BB Lower", showlegend=False), row=1, col=1)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["MA20"], line=dict(color="orange", width=1.5, dash="dash"), name="20日移動平均"), row=1, col=1)
                
                if not df_markers.empty:
                    fig.add_trace(gr.Scatter(x=df_markers["date"], y=df_markers["price"], mode="markers", marker=dict(symbol="triangle-up", size=16, color="#E0B0FF", line=dict(color="#AA00FF", width=2)), text=df_markers.apply(lambda r: f"{r['insider']}<br>購入額: ${r['value']:,.0f}", axis=1), hoverinfo="text+x+y", name="インサイダー買い"), row=1, col=1)
                
                if show_rsi:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["RSI"], line=dict(color="orange", width=1.5), name="RSI (14)"), row=1, col=2)
                    fig.add_hline(y=70, line_dash="dash", line_color="red", row=1, col=2, opacity=0.5)
                    fig.add_hline(y=30, line_dash="dash", line_color="green", row=1, col=2, opacity=0.5)
                
                fig.update_layout(height=450, template="plotly_dark", paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig, use_container_width=True)

            elif "重複" in chart_layout_mode:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                
                if chart_type == "ローソク足":
                    fig.add_trace(gr.Candlestick(x=df_prices.index, open=df_prices["Open"], high=df_prices["High"], low=df_prices["Low"], close=df_prices["Close"], name="株価 (OHLC)"), secondary_y=False)
                else:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["Close"], mode="lines", line=dict(color="#00FFCC", width=2), name="終値"), secondary_y=False)
                
                if show_bb:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.15)", width=1, dash="dash"), name="BB Upper", showlegend=False), secondary_y=False)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.15)", width=1, dash="dash"), fill="tonexty", fillcolor="rgba(0, 255, 204, 0.02)", name="BB Lower", showlegend=False), secondary_y=False)
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["MA20"], line=dict(color="orange", width=1.5, dash="dash"), name="20日移動平均"), secondary_y=False)
                
                if not df_markers.empty:
                    fig.add_trace(gr.Scatter(x=df_markers["date"], y=df_markers["price"], mode="markers", marker=dict(symbol="triangle-up", size=16, color="#E0B0FF", line=dict(color="#AA00FF", width=2)), text=df_markers.apply(lambda r: f"{r['insider']}<br>購入額: ${r['value']:,.0f}", axis=1), hoverinfo="text+x+y", name="インサイダー買い"), secondary_y=False)
                
                if show_rsi:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["RSI"], line=dict(color="rgba(255, 165, 0, 0.4)", width=1.5), name="RSI (14) [右軸]"), secondary_y=True)
                    fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 0, 0, 0.3)", secondary_y=True)
                    fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 0, 0.3)", secondary_y=True)
                    fig.update_yaxes(title_text="RSI", range=[0, 100], secondary_y=True, showgrid=False)
                
                fig.update_yaxes(title_text="株価 ($)", secondary_y=False)
                fig.update_layout(height=600, template="plotly_dark", paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ 選択された銘柄の株価データを取得できませんでした。")
