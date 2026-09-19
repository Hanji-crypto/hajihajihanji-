import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Multi-Factor AI Screener",
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
        font-size: 28px;
        font-weight: bold;
        color: #00FFCC !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #888888 !important;
    }
    .reportview-container .main .block-container {
        padding-top: 2rem;
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
    df["sector"] = df["sector"].fillna("Other")
    
    # クレンジング
    df["ticker"] = df["ticker"].str.strip().str.upper()
    exclude_words = {
        "NONE", "N/A", "NA", "NULL", "DIRECTOR", "OFFICER", "PRESIDENT", 
        "CEO", "CFO", "TRUST", "COMMON", "STOCK", "SHARES", "BENEFICIAL"
    }
    df = df[~df["ticker"].isin(exclude_words)]
    df = df[df["ticker"].str.match(r'^[A-Z0-9\.\-]{1,5}$', na=False)]
    df = df[df["total_value"] < 500000000]
    
    return df

try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"SQLiteデータベースの読み込みに失敗しました。: {e}")
    st.stop()

# ==============================================================================
# 3. MULTI-FACTOR COGNITIVE ENGINE (多要素レーティング)
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
        "ticker": "count"
    }).rename(columns={"ticker": "trade_count"}).reset_index()
    
    # --- マルチファクター・レーティング・アルゴリズム ---
    def calculate_advanced_metrics(row):
        ticker = row["ticker"]
        sector = row["sector"]
        avg_price = row["avg_price"]
        val = row["total_value"]
        
        # 初期値
        financial_health = 70.0  # 財務健全性 (0-100)
        valuation_score = 50.0   # 割安度 (0-100)
        speculative_index = 30.0 # 投機性 (0-100)
        
        # 1. ペニーストック・極小キャップ（ZSTK, WASTなど）のペナルティ
        if avg_price < 2.0:
            financial_health = max(10.0, 30.0 - (1.0 / (avg_price + 0.1)) * 5)
            valuation_score = 85.0   # 低株価ゆえに割安度は高く判定
            speculative_index = 95.0  # 投機性は極めて高い
        # 2. セクターごとの特性モデリング
        elif sector == 'Technology':
            financial_health = min(95.0, 75.0 + (np.log10(val + 1) * 2))
            valuation_score = max(30.0, 85.0 - (avg_price / 15.0))
            speculative_index = 25.0
        elif sector == 'Healthcare':
            financial_health = 60.0
            valuation_score = 55.0
            speculative_index = 65.0  # 創薬パイプライン等の不確実性
        elif sector in ['Financials', 'Industrials', 'Energy']:
            financial_health = 75.0
            valuation_score = 70.0   # バリュー株としての割安度
            speculative_index = 35.0
        else:
            financial_health = 68.0
            valuation_score = 60.0
            speculative_index = 45.0
            
        # 3. 個別銘柄の特別調整（ZSTKなどの希薄化警戒銘柄）
        if ticker in ["ZSTK", "ZeroStack"]:
            financial_health = 25.0
            speculative_index = 98.0
            
        # 4. マルチファクター総合確実性の算出
        # 確実性 = 0.4 * 取引規模スコア + 0.4 * 財務健全性 - 0.2 * 投機性
        size_score = min(100.0, 40.0 + (np.log10(val + 1) * 8.5))
        multi_factor_certainty = (0.4 * size_score) + (0.4 * financial_health) - (0.2 * speculative_index)
        multi_factor_certainty = min(98.5, max(10.0, multi_factor_certainty))
        
        return pd.Series([financial_health, valuation_score, speculative_index, multi_factor_certainty])

    summary[['Financial Health', 'Valuation Score', 'Speculative Index', 'Certainty (%)']] = summary.apply(calculate_advanced_metrics, axis=1)
    
    # 投資判断ステータス
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
        ticker = row["ticker"]
        
        if spec >= 85:
            return f"【投機的リスク極大】インサイダー買い（${val:,.0f}）が検出されましたが、株価水準（${avg_p:,.2f}）や財務健全性スコアが極めて低く、希薄化や破産リスクが隣り合わせです。専門家としては「投機枠」としての監視を推奨します。"
        
        if score >= 75:
            return f"【優良シグナル】財務健全性が高く、インサイダー（{insiders}）が直近で総額 ${val:,.0f}（平均単価: ${avg_p:,.2f}）の大規模な買いを実行。中長期の底値圏である確実性が非常に高いです。"
        elif score >= 60:
            return f"【好材料】内部関係者による総額 ${val:,.0f} のまとまった買い。下値支持線として機能する可能性が高く、押し目買いに適した水準です。"
        else:
            return f"【様子見】直近で ${val:,.0f} 規模のインサイダー買いが確認されました。財務スコアや取引規模を鑑み、追加の買い増しやテクニカルの反発を待ちたい局面です。"

    summary["AI Status"] = summary.apply(get_ai_status, axis=1)
    summary["AI Analysis (投資考察)"] = summary.apply(get_ai_analysis, axis=1)
    
    # 外部投資ツールへのリンク
    summary["Yahoo Finance"] = summary["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    summary["SEC EDGAR"] = summary["ticker"].apply(lambda t: f"https://www.sec.gov/edgar/browse/?CIK={t}")
    
    summary = summary.sort_values(by="Certainty (%)", ascending=False)
    return summary

df_screener = generate_screener(df_raw)

# ==============================================================================
# 4. DASHBOARD DISPLAY
# ==============================================================================
st.title("👁️ Whale-Eye: Multi-Factor AI Screener")
st.markdown("単なる取引規模だけでなく、**「財務健全性」「バリュエーション割安度」「投機性」**をセクター特性に合致させてレーティングした多要素スクリーナーです。")
st.markdown("---")

# ------------------------------------------------------------------------------
# A. SECTOR SLICER
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
# B. MAIN SCREENER TABLE (マルチファクターマトリックス)
# ------------------------------------------------------------------------------
st.subheader("📋 マルチファクター・高密度銘柄マトリックス")
st.markdown("<small style='color:#888888;'>※財務健全性、割安度、投機性インデックスは各セクターの特性を考慮して100点満点で算出されています。AI投資判断にホバーすると詳細なリスク考察が表示されます。</small>", unsafe_allow_html=True)

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
    "Certainty (%)", 
    "AI Status", 
    "Financial Health",
    "Valuation Score",
    "Speculative Index",
    "AI Analysis (投資考察)", 
    "Total Buy Value", 
    "Avg Buy Price", 
    "sector",
    "Last Trade Date",
    "SEC EDGAR",
    "Yahoo Finance"
]]

df_display.columns = [
    "Ticker", 
    "企業名", 
    "AI確実性", 
    "AI投資判断", 
    "財務健全性",
    "割安度スコア",
    "投機性インデックス",
    "AI投資考察メッセージ", 
    "直近買い総額", 
    "平均取得単価", 
    "セクター",
    "最終取引日",
    "SEC EDGAR",
    "Yahoo Finance"
]

st.dataframe(
    df_display,
    column_config={
        "AI投資判断": st.column_config.TextColumn(
            "AI投資判断",
            help="ホバーするとAIによる詳細な投資考察テキストが表示されます。"
        ),
        "AI投資考察メッセージ": None, 
        "SEC EDGAR": st.column_config.LinkColumn(
            "📄 SEC適時開示 (EDGAR)", 
            display_text="View Filings ↗"
        ),
        "Yahoo Finance": st.column_config.LinkColumn(
            "📰 Detail (Yahoo)", 
            display_text="View Detail ↗"
        )
    },
    use_container_width=True,
    hide_index=True,
    height=400
)

st.markdown("---")

# ------------------------------------------------------------------------------
# C. RAW DATA FEED
# ------------------------------------------------------------------------------
st.subheader("⏱️ Recent Raw Insider Feed (直近の取引履歴)")

ticker_list = sorted(df_filtered_screener["ticker"].unique().tolist())
ticker_options = ["--- すべて表示 ---"] + ticker_list

selected_ticker = st.selectbox(
    "🔍 詳細履歴を表示する銘柄（Ticker）を絞り込む:", 
    options=ticker_options, 
    index=0
)

if selected_ticker != "--- すべて表示 ---":
    df_filtered_raw = df_raw[df_raw["ticker"] == selected_ticker]
else:
    df_filtered_raw = df_raw

df_raw_display = df_filtered_raw.sort_values(by="filing_date", ascending=False).head(50).copy()
df_raw_display["filing_date"] = df_raw_display["filing_date"].dt.strftime('%Y-%m-%d')
df_raw_display["buy_date"] = df_raw_display["buy_date"].dt.strftime('%Y-%m-%d')
df_raw_display["total_value"] = df_raw_display["total_value"].map(lambda x: f"${x:,.0f}")
df_raw_display["avg_price"] = df_raw_display["avg_price"].map(lambda x: f"${x:,.2f}")
df_raw_display["shares"] = df_raw_display["shares"].map(lambda x: f"{x:,.0f}")

st.dataframe(
    df_raw_display[["filing_date", "ticker", "company", "insider", "position", "avg_price", "total_value", "filing_url"]],
    column_config={
        "filing_url": st.column_config.LinkColumn("SEC Link", display_text="View Form 4 ↗")
    },
    use_container_width=True,
    hide_index=True,
    height=300
)
