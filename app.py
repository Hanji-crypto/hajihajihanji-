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
    /* キーボードショートカットガイドのスタイル */
    .kb-guide {
        background-color: #1A1F2C;
        border: 1px solid #2D3748;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 12px;
        color: #A0AEC0;
        margin-bottom: 10px;
    }
    .kb-key {
        background-color: #2D3748;
        color: #FFF;
        padding: 2px 6px;
        border-radius: 4px;
        font-family: monospace;
        font-weight: bold;
        border-bottom: 2px solid #1A202C;
    }
    /* ⚡ 【新設】リアルタイム・イベント・コンソールのスタイル */
    .event-console {
        background-color: #111622;
        border: 1px solid #1F2937;
        border-radius: 8px;
        padding: 15px;
        max-height: 220px;
        overflow-y: auto;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 13px;
        line-height: 1.6;
        margin-bottom: 15px;
    }
    .console-row {
        border-bottom: 1px solid #1E293B;
        padding: 6px 0;
        display: flex;
        align-items: flex-start;
    }
    .console-date {
        color: #888888;
        min-width: 95px;
        font-weight: bold;
    }
    .console-badge {
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
        margin-right: 10px;
        min-width: 110px;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# TickerをURL検索に引っかからないように％エンコードする関数
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
            
        healthcare_tickers = {"CYBN", "ARTV", "ZSTK", "LLY", "MRNA", "PFE", "BIIB", "GILD", "SMMT"}
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
        if any(x in company_lower for x in ["biotherapeutics", "pharma", "therapeutics", "biosciences", "health", "medical", "cancer", "summit"]):
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
        spec = row["Speculative Index"]
        score = row["Certainty (%)"]
        if spec >= 85:
            return "🚨 投機的警戒"
        elif score >= 75:
            return "🔥 強気推奨"
        elif score >= 60:
            return "🟢 押し目推奨"
        else:
            return "🟡 様子見"
            
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
    
    summary["encoded_ticker"] = summary["ticker"].apply(encode_ticker_for_search_avoidance)
    summary["Finviz Chart"] = "https://finviz.com/quote.ashx?t=" + summary["encoded_ticker"]
    summary["Yahoo Finance"] = "https://finance.yahoo.com/quote/" + summary["encoded_ticker"]
    summary["SEC EDGAR"] = "https://www.sec.gov/edgar/browse/?CIK=" + summary["encoded_ticker"]
    
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
# B. MAIN SCREENER TABLE & KEYBOARD SHORTCUTS
# ------------------------------------------------------------------------------
st.subheader("📋 マルチファクター・高密度銘柄マトリックス")

st.markdown("""
    <div class="kb-guide">
        ⌨️ <b>プロフェッショナル・キーボード操作ガイド:</b><br>
        1. 右上の 🔍 検索窓に <code>smmt</code> 等を入力して <span class="kb-key">Enter</span>。<br>
        2. <span class="kb-key">Shift + Tab</span> キーを数回押してテーブル内にフォーカスを移動。<br>
        3. 矢印キー <span class="kb-key">↑</span> <span class="kb-key">↓</span> で銘柄を選択し、<b><span class="kb-key">X</span> キー</b> または <b><span class="kb-key">Enter</span> キー</b> を押すことでチェックボックスをON/OFFできます。
    </div>
""", unsafe_allow_html=True)

# 表示用にデータフレームを整形
df_display = df_filtered_screener.copy()
df_display["Certainty (%)"] = df_display["Certainty (%)"].map(lambda x: f"{x:.1f}%")
df_display["Financial Health"] = df_display["Financial Health"].map(lambda x: f"{x:.1f}/100")
df_display["Valuation Score"] = df_display["Valuation Score"].map(lambda x: f"{x:.1f}/100")
df_display["Speculative Index"] = df_display["Speculative Index"].map(lambda x: f"{x:.1f}/100")
df_display["Total Buy Value"] = df_display["total_value"].map(lambda x: f"${x:,.0f}")
df_display["Avg Buy Price"] = df_display["avg_price"].map(lambda x: f"${x:,.2f}")
df_display["Last Trade Date"] = df_display["buy_date"].dt.strftime('%Y-%m-%d')

df_display_table = pd.DataFrame()
df_display_table["Ticker"] = df_display["ticker"]
df_display_table["企業名"] = df_display["company"]
df_display_table["Finviz Chart"] = df_display["Finviz Chart"]
df_display_table["AI投資判断"] = df_display["AI Status"]
df_display_table["AI確実性"] = df_display["Certainty (%)"]
df_display_table["財務健全性"] = df_display["Financial Health"]
df_display_table["割安度スコア"] = df_display["Valuation Score"]
df_display_table["投機性インデックス"] = df_display["Speculative Index"]
df_display_table["直近買い総額"] = df_display["Total Buy Value"]
df_display_table["平均取得単価"] = df_display["Avg Buy Price"]
df_display_table["最終取引日"] = df_display["Last Trade Date"]
df_display_table["セクター"] = df_display["sector"]
df_display_table["SEC EDGAR"] = df_display["SEC EDGAR"]
df_display_table["Yahoo Finance"] = df_display["Yahoo Finance"]

# Ticker列で重複を完全に排除し、1銘柄1行のみにする
df_display_table = df_display_table.drop_duplicates(subset=["Ticker"])

event = st.dataframe(
    df_display_table,
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
        selected_tickers = [df_display_table.iloc[r]["Ticker"] for r in selected_rows]

# 選択がない場合は、デフォルトでテーブルの1行目を選択状態にする
if not selected_tickers and not df_display_table.empty:
    selected_tickers = [df_display_table.iloc[0]["Ticker"]]

st.markdown("---")

# ==============================================================================
# 5. DYNAMIC ANALYTICS TERMINAL (AI考察 ＆ 取引履歴)
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
    # 6. CATALYST INTEGRATED OVERLAY CHART SYSTEM (完全分離・専用コンソール版)
    # ==============================================================================
    st.markdown("### 📈 インサイダー買い・テクニカルチャート / 複数銘柄パフォーマンス比較")
    
    is_comparison_mode = len(selected_tickers) > 1
    
    # コントロールパネル
    if is_comparison_mode:
        ctrl_col1, ctrl_col2 = st.columns([2, 5])
        with ctrl_col1:
            chart_layout_mode = st.selectbox("📊 比較モード", options=["相対パフォーマンス比較 (%)", "個別絶対価格重ね書き ($)"], index=0)
        show_bb = False
        show_rsi = False
        chart_type = "折れ線"
    else:
        ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 3])
        with ctrl_col1:
            show_bb = st.checkbox("ボリンジャーバンドを表示", value=True)
        with ctrl_col2:
            show_rsi = st.checkbox("RSI (14) を表示", value=True)
        with ctrl_col3:
            chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)

    # yfinanceから安全に株価を取得
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

    # カタリスト取得ロジック
    @st.cache_data(ttl=7200)
    def fetch_catalyst_events(ticker, df_prices, df_raw_trades):
        events = []
        
        # 1. yfinance ニュースからの自動抽出
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
        except Exception as e:
            pass

        # 2. 超強力フォールバック（超大口取引や役職取引）
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
        except Exception as e:
            pass

        return pd.DataFrame(events).drop_duplicates(subset=["date", "category"]) if events else pd.DataFrame()

    with st.spinner("株価データを取得中..."):
        df_prices_map = fetch_multiple_stock_prices(selected_tickers)

    # --- CHART GENERATION LOGIC ---
    if df_prices_map:
        if is_comparison_mode:
            # ==========================================
            # 複数銘柄比較チャート
            # ==========================================
            fig = gr.Figure()
            for t, df_prices in df_prices_map.items():
                if df_prices.empty:
                    continue
                if "相対パフォーマンス比較 (%)" in chart_layout_mode:
                    base_price = df_prices["Close"].iloc[0]
                    relative_perf = ((df_prices["Close"] - base_price) / base_price) * 100
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=relative_perf, mode="lines", name=f"{t} 相対推移 (%)", line=dict(width=2)))
                    y_axis_title = "相対パフォーマンス (%)"
                else:
                    fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["Close"], mode="lines", name=f"{t} 株価 ($)", line=dict(width=2)))
                    y_axis_title = "株価 ($)"

            fig.update_layout(
                height=500, template="plotly_dark", paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                yaxis_title=y_axis_title, xaxis_title="日付",
                margin=dict(l=20, r=20, t=20, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            # ==========================================
            # 単一銘柄特化：2段構成 ＆ 【右株価・左RSI】
            # ==========================================
            t = selected_tickers[0]
            df_prices = df_prices_map[t]
            
            # テクニカル計算
            df_prices["MA20"] = df_prices["Close"].rolling(window=20).mean()
            df_prices["STD20"] = df_prices["Close"].rolling(window=20).std()
            df_prices["BB_Upper"] = df_prices["MA20"] + (df_prices["STD20"] * 2)
            df_prices["BB_Lower"] = df_prices["MA20"] - (df_prices["STD20"] * 2)
            
            delta = df_prices["Close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-9)
            df_prices["RSI"] = 100 - (100 / (1 + rs))
            
            fig = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.05, 
                row_heights=[0.75, 0.25],
                specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
            )
            
            # --------------------------------------------------
            # ROW 1: 【右株価・左RSI】
            # --------------------------------------------------
            if show_rsi:
                fig.add_trace(gr.Scatter(
                    x=df_prices.index, y=df_prices["RSI"],
                    line=dict(color="rgba(255, 165, 0, 0.45)", width=1.5), 
                    name="RSI (14)",
                    hoverinfo="y"  # 👈 最小限の数値情報のみ
                ), row=1, col=1, secondary_y=False)
                fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 0, 0, 0.25)", row=1, col=1, secondary_y=False)
                fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 0, 0.25)", row=1, col=1, secondary_y=False)
                fig.update_yaxes(title_text="RSI", range=[0, 100], row=1, col=1, secondary_y=False)

            if chart_type == "ローソク足":
                fig.add_trace(gr.Candlestick(
                    x=df_prices.index, open=df_prices["Open"], high=df_prices["High"], low=df_prices["Low"], close=df_prices["Close"], 
                    name="株価 (OHLC)",
                    hoverinfo="x+y"  # 👈 最小限の数値情報のみ
                ), row=1, col=1, secondary_y=True)
            else:
                fig.add_trace(gr.Scatter(
                    x=df_prices.index, y=df_prices["Close"], mode="lines", 
                    line=dict(color="#00FFCC", width=2), name="終値",
                    hoverinfo="x+y"
                ), row=1, col=1, secondary_y=True)
            
            if show_bb:
                fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.12)", width=0.8, dash="dash"), name="BB Upper", hoverinfo="skip", showlegend=False), row=1, col=1, secondary_y=True)
                fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.12)", width=0.8, dash="dash"), fill="tonexty", fillcolor="rgba(0, 255, 204, 0.015)", name="BB Lower", hoverinfo="skip", showlegend=False), row=1, col=1, secondary_y=True)
                fig.add_trace(gr.Scatter(x=df_prices.index, y=df_prices["MA20"], line=dict(color="orange", width=1.2, dash="dash"), name="20日移動平均", hoverinfo="skip"), row=1, col=1, secondary_y=True)
            
            fig.update_yaxes(title_text="株価 ($)", row=1, col=1, secondary_y=True)

            # --------------------------------------------------
            # ROW 2: 出来高 ＆ インサイダー量 (軸分離)
            # --------------------------------------------------
            fig.add_trace(gr.Bar(
                x=df_prices.index, y=df_prices["Volume"],
                name="市場出来高 (Volume)",
                marker_color="rgba(128, 128, 128, 0.25)",
                hoverinfo="y"
            ), row=2, col=1, secondary_y=False)
            
            df_ticker_raw = df_raw[df_raw["ticker"] == t].copy()
            df_insider_daily = df_ticker_raw.groupby("buy_date")["total_value"].sum().reset_index()
            df_insider_daily = df_insider_daily[df_insider_daily["buy_date"].isin(df_prices.index)]
            
            if not df_insider_daily.empty:
                fig.add_trace(gr.Bar(
                    x=df_insider_daily["buy_date"], y=df_insider_daily["total_value"],
                    name="インサイダー取引量 (USD)",
                    marker_color="#AA00FF",
                    width=1000 * 60 * 60 * 24 * 3,
                    hoverinfo="y"
                ), row=2, col=1, secondary_y=True)
                
            fig.update_yaxes(title_text="出来高 (Vol)", row=2, col=1, secondary_y=False)
            fig.update_yaxes(title_text="インサイダー量 ($)", row=2, col=1, secondary_y=True, showgrid=False)

            # --------------------------------------------------
            # ⚡ 【完全分離設計】データ収集 ＆ 専用コンソールHTML生成
            # --------------------------------------------------
            min_price = df_prices["Low"].min()
            event_y_line = min_price * 0.93
            
            linked_sources_list = []
            raw_events_by_date = {}

            color_palette = ["#00FFCC", "#FF00FF", "#00FF00", "#FF9900", "#00FFFF", "#FFFF00"]
            unique_insiders_list = list(df_ticker_raw["insider"].unique())
            insider_colors = {name: color_palette[i % len(color_palette)] for i, name in enumerate(unique_insiders_list)}

            # ① 同日・同インサイダーの取引を完全に合算
            df_insider_grouped = df_ticker_raw.groupby(["buy_date", "insider"]).agg({
                "total_value": "sum",
                "position": "first",
                "filing_url": "first"
            }).reset_index()

            for _, trade in df_insider_grouped.iterrows():
                trade_date = trade["buy_date"]
                closest_date_idx = df_prices.index.get_indexer([trade_date], method="nearest")[0]
                closest_date = df_prices.index[closest_date_idx]
                val = trade["total_value"]
                insider_name = trade["insider"]
                pos = trade["position"]
                f_url = trade["filing_url"] if pd.notna(trade["filing_url"]) else f"https://www.sec.gov/edgar/browse/?CIK={t}"
                
                date_str = closest_date.strftime('%Y-%m-%d')
                prev_day = (closest_date - timedelta(days=1)).strftime('%Y-%m-%d')
                next_day = (closest_date + timedelta(days=1)).strftime('%Y-%m-%d')
                date_specific_news_url = f"https://www.google.com/search?q={t}+stock+news+after:{prev_day}+before:{next_day}&tbm=nws"
                
                linked_sources_list.append({
                    "date": date_str,
                    "type": "🟣 インサイダー [ I ]",
                    "event": f"{insider_name} ({pos}) が 合計 ${val:,.0f} を購入",
                    "sec_url": f_url,
                    "yahoo_url": date_specific_news_url,
                    "finviz_url": f"https://finviz.com/quote.ashx?t={t}"
                })

                if closest_date not in raw_events_by_date:
                    raw_events_by_date[closest_date] = []
                
                color = insider_colors.get(insider_name, "#00FFCC")
                raw_events_by_date[closest_date].append({
                    "type": "I",
                    "badge_html": f"<span class='console-badge' style='background-color: rgba(170, 0, 255, 0.15); color: #E0B0FF; border: 1px solid #AA00FF;'>インサイダー [ I ]</span>",
                    "text_html": f"👤 <span style='color:{color}; font-weight:bold;'>{insider_name}</span> ({pos}) が 合計 <b style='color:#00FFCC;'>${val:,.0f}</b> を市場から購入"
                })

            # ② カタリスト（ニュース・決算）の収集
            df_catalysts = fetch_catalyst_events(t, df_prices, df_raw)
            if not df_catalysts.empty:
                for _, row in df_catalysts.iterrows():
                    c_date = pd.to_datetime(row["date"])
                    if c_date in df_prices.index:
                        is_earnings = "決算" in row["category"]
                        type_label = "🔴 決算 [ E ]" if is_earnings else "🟡 カタリスト [ R ]"
                        
                        date_str = c_date.strftime('%Y-%m-%d')
                        prev_day = (c_date - timedelta(days=1)).strftime('%Y-%m-%d')
                        next_day = (c_date + timedelta(days=1)).strftime('%Y-%m-%d')
                        date_specific_news_url = f"https://www.google.com/search?q={t}+stock+news+after:{prev_day}+before:{next_day}&tbm=nws"
                        
                        linked_sources_list.append({
                            "date": date_str,
                            "type": type_label,
                            "event": f"【{row['category']}】 {row['title']}",
                            "sec_url": f"https://www.sec.gov/edgar/browse/?CIK={t}",
                            "yahoo_url": date_specific_news_url,
                            "finviz_url": f"https://finviz.com/quote.ashx?t={t}"
                        })

                        if c_date not in raw_events_by_date:
                            raw_events_by_date[c_date] = []
                        
                        if is_earnings:
                            badge = "<span class='console-badge' style='background-color: rgba(255, 68, 68, 0.15); color: #FF8888; border: 1px solid #FF4444;'>決算発表 [ E ]</span>"
                            text_color = "#FF8888"
                        else:
                            badge = "<span class='console-badge' style='background-color: rgba(255, 215, 0, 0.15); color: #FFD700; border: 1px solid #FFD700;'>ニュース [ R ]</span>"
                            text_color = "#FFD700"

                        raw_events_by_date[c_date].append({
                            "type": "E" if is_earnings else "R",
                            "badge_html": badge,
                            "text_html": f"📢 <span style='color:{text_color};'>{row['category']}</span>: {row['title']}"
                        })

            # --------------------------------------------------
            # 🖥️ 【新設】リアルタイム・イベント・コンソール（専用表示スペース）の描画
            # --------------------------------------------------
            st.markdown(f"#### 👁️ 【{t}】 リアルタイム・イベント・コンソール")
            
            if raw_events_by_date:
                console_html = "<div class='event-console'>"
                # 日付の新しい順にソートしてタイムラインを生成
                for event_date in sorted(raw_events_by_date.keys(), reverse=True):
                    date_str = event_date.strftime('%Y-%m-%d')
                    for item in raw_events_by_date[event_date]:
                        console_html += f"""
                            <div class='console-row'>
                                <div class='console-date'>[{date_str}]</div>
                                {item['badge_html']}
                                <div class='console-text'>{item['text_html']}</div>
                            </div>
                        """
                console_html += "</div>"
                st.markdown(console_html, unsafe_allow_html=True)
            else:
                st.info("💡 直近1年間で検出された重大イベントはありません。")

            # --------------------------------------------------
            # ③ チャート上へのイベントマーカープロット（ホバーは100%無効化）
            # --------------------------------------------------
            for event_date, items in raw_events_by_date.items():
                unique_types = list(set([item["type"] for item in items]))
                
                if len(unique_types) > 1:
                    marker_char = "★"
                    marker_color = "#00FFCC"
                    border_color = "#FFFFFF"
                else:
                    single_type = unique_types[0]
                    if single_type == "I":
                        marker_char = "I"
                        marker_color = "#AA00FF"
                        border_color = "#E0B0FF"
                    elif single_type == "E":
                        marker_char = "E"
                        marker_color = "#FF4444"
                        border_color = "#FFFFFF"
                    else:
                        marker_char = "R"
                        marker_color = "#FFD700"
                        border_color = "#FFFFFF"

                # ⚡ hoverinfo="skip" に設定し、チャート上での重複ホバーを完全に防止！
                fig.add_trace(gr.Scatter(
                    x=[event_date], y=[event_y_line],
                    mode="markers+text",
                    marker=dict(symbol="square", size=18, color=marker_color, line=dict(color=border_color, width=1)),
                    text=[marker_char],
                    textposition="middle center",
                    textfont=dict(color="white" if marker_char != "R" else "black", size=10, family="Arial Black"),
                    hoverinfo="skip",  # 👈 巨大なホバーの発生を100%防止
                    showlegend=False
                ), row=1, col=1, secondary_y=True)

                if marker_char in ["★", "E"]:
                    fig.add_vline(x=event_date, line_dash="dot", line_color="rgba(0, 255, 204, 0.2)" if marker_char == "★" else "rgba(255, 68, 68, 0.2)", row=1, col=1, secondary_y=True)

            # チャートのホバー設定（数値のみの極小ホバー）
            fig.update_layout(
                height=700,
                template="plotly_dark",
                paper_bgcolor="#0E1117",
                plot_bgcolor="#0E1117",
                xaxis_rangeslider_visible=False,
                margin=dict(l=20, r=20, t=20, b=20),
                hovermode="x",  # 👈 個別ホバー
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hoverlabel=dict(
                    bgcolor="rgba(26, 31, 44, 0.85)",
                    bordercolor="rgba(255, 255, 255, 0.1)",
                    font_size=11,
                    font_family="Arial"
                )
            )
            
            st.plotly_chart(fig, use_container_width=True)

            # ==========================================
            # 🔗 【合算版】マルチソース・ターミナル
            # ==========================================
            st.markdown(f"### 🔗 【{t}】 イベント＆マルチソース・ターミナル")
            
            if linked_sources_list:
                df_sources = pd.DataFrame(linked_sources_list).sort_values(by="date", ascending=False)
                df_sources = df_sources.drop_duplicates(subset=["date", "event"])
                
                st.dataframe(
                    df_sources,
                    column_config={
                        "date": st.column_config.TextColumn("日付", width="small"),
                        "type": st.column_config.TextColumn("分類", width="small"),
                        "event": st.column_config.TextColumn("イベント", width="large"),
                        "sec_url": st.column_config.LinkColumn("SEC開示", display_text="Form 4 ↗", width="small"),
                        "yahoo_url": st.column_config.LinkColumn("Yahooニュース", display_text="News ↗", width="small"),
                        "finviz_url": st.column_config.LinkColumn("Finviz", display_text="Chart ↗", width="small")
                    },
                    use_container_width=True,
                    hide_index=True,
                    height=250
                )
            else:
                st.info("💡 直近1年間で検出された重大イベントはありません。")
            
    else:
        st.warning("⚠️ 選択された銘柄の株価データを取得できませんでした。")
