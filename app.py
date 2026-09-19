import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Insider AI Screener & Risk Monitor",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# カスタムCSSで完全なダークテーマと洗練されたカードUIを適用
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
    /* テーブル内のリンクを目立たせる */
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
# 2. DATA LOADING & AGGREGATION
# ==============================================================================
@st.cache_data(ttl=600) # 10分キャッシュ
def load_and_process_data():
    conn = sqlite3.connect("insider.db")
    
    # テーブルの列名を確認し、セクター情報(sector)があれば取得、なければ 'Other' で補完する
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
    
    # 型変換
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce')
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors='coerce')
    df["shares"] = pd.to_numeric(df["shares"], errors='coerce')
    
    # セクターの欠損値補完
    df["sector"] = df["sector"].fillna("Other")
    
    # --- 株式投資専門家基準によるデータクレンジング ---
    df["ticker"] = df["ticker"].str.strip().str.upper()
    
    # 明らかなシステム誤判定（ノイズ）の除外リスト
    exclude_words = {
        "NONE", "N/A", "NA", "NULL", "DIRECTOR", "OFFICER", "PRESIDENT", 
        "CEO", "CFO", "TRUST", "COMMON", "STOCK", "SHARES", "BENEFICIAL"
    }
    df = df[~df["ticker"].isin(exclude_words)]
    
    # フォーマットバリデーション（1〜5文字の英数字）
    df = df[df["ticker"].str.match(r'^[A-Z0-9\.\-]{1,5}$', na=False)]
    
    # 異常データのクリーニング (5億ドル以上の極端な単一取引はデータエラーの可能性が高いため除外)
    df = df[df["total_value"] < 500000000]
    
    return df

try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"SQLiteデータベースの読み込みに失敗しました。: {e}")
    st.stop()

# ==============================================================================
# 3. AI COGNITIVE ENGINE (投機的リスク監視機能付き)
# ==============================================================================
def generate_screener(df):
    # 銘柄（Ticker）ごとに集計
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
    
    # AI確実性とステータスの算出
    summary["Certainty (%)"] = summary["total_value"].apply(
        lambda val: min(98.5, max(50.0, 50.0 + (np.log10(val + 1) * 7.5)))
    )
    
    # 投機的リスク（ZSTK/ZeroStack、その他超低単価・急激なファイナンス懸念銘柄）の判定
    def evaluate_speculative_risk(row):
        ticker = row["ticker"]
        avg_p = row["avg_price"]
        
        # 1. 特定の厳重警戒銘柄（ZSTKなど、現在進行形で希薄化・組織再編中のもの）
        if ticker in ["ZSTK", "ZeroStack"]:
            return "⚠️ 希薄化・組織再編リスク（高ボラティリティ）"
            
        # 2. ペニーストック基準（平均取得単価が1ドル未満の超低位株は、破産・上場廃止リスクが極めて高い）
        if avg_p < 1.0:
            return "⚠️ ペニーストック（上場廃止・破産リスク高）"
            
        return "🟢 正常（主要リスク未検出）"

    summary["Risk Status"] = summary.apply(evaluate_speculative_risk, axis=1)
    
    def get_ai_status(row):
        score = row["Certainty (%)"]
        risk = row["Risk Status"]
        
        if "⚠️" in risk:
            return "🚨 投機的警戒 (High Risk Speculative)"
        
        if score >= 85:
            return "🔥 強気 (Strong Buy)"
        elif score >= 70:
            return "🟢 押し目推奨 (Accumulate)"
        else:
            return "🟡 様子見 (Hold/Watch)"
            
    def get_ai_analysis(row):
        score = row["Certainty (%)"]
        val = row["total_value"]
        insiders = row["insider"]
        avg_p = row["avg_price"]
        risk = row["Risk Status"]
        ticker = row["ticker"]
        
        if "⚠️" in risk:
            if ticker == "ZSTK":
                return f"【厳重警戒】インサイダー買い（${val:,.0f}）が入っていますが、直近で大規模な資金調達合意（8-K）や合併関連書類（S-4）を相次いで提出しており、株式価値の希薄化および極めて高いボラティリティリスクがあります。投機的要素が強く、初心者には推奨されません。"
            else:
                return f"【ペニーストック警戒】取得単価が ${avg_p:,.2f} と極めて低く、上場廃止や財務健全性（破産リスク）の懸念が拭えません。インサイダーの買い越し（${val:,.0f}）があっても、投機的な枠内での取引に留めるべきです。"
        
        if score >= 85:
            return f"【超強力シグナル】インサイダー（{insiders}等）が直近で総額 ${val:,.0f}（平均単価: ${avg_p:,.2f}）の極めて大規模な買いを実行。内部関係者の絶対的な自信の現れであり、中長期の底値圏である確実性が非常に高いです。"
        elif score >= 70:
            return f"【好材料】内部関係者による総額 ${val:,.0f} のまとまった買いが観測されています。下値支持線として機能する可能性が高く、押し目買いに適した水準です。"
        else:
            return f"【監視対象】直近で ${val:,.0f} 規模 of インサイダー買いが確認されました。まだ規模が小さいため、追加の買い増しやテクニカルの反発を待ちたい局面です。"

    summary["AI Status"] = summary.apply(get_ai_status, axis=1)
    summary["AI Analysis (投資考察)"] = summary.apply(get_ai_analysis, axis=1)
    
    # 外部投資ツールへのリンク作成
    summary["Finviz Chart"] = summary["ticker"].apply(lambda t: f"https://finviz.com/quote.ashx?t={t}")
    summary["Yahoo Finance"] = summary["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    summary["SEC EDGAR"] = summary["ticker"].apply(lambda t: f"https://www.sec.gov/edgar/browse/?CIK={t}")
    
    summary = summary.sort_values(by="Certainty (%)", ascending=False)
    return summary

df_screener = generate_screener(df_raw)

# ==============================================================================
# 4. DASHBOARD DISPLAY
# ==============================================================================
st.title("👁️ Whale-Eye AI Screener & Risk Monitor")
st.markdown("大口インサイダー取引データからAI確実性を算出し、同時に**「財務健全性・希薄化・破産リスク」**を日次でスクリーニングします。")
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
# B. MAIN SCREENER TABLE (リスク警告・SECリンク統合マトリックス)
# ------------------------------------------------------------------------------
st.subheader("📋 スライサー連動・高密度銘柄マトリックス")
st.markdown("<small style='color:#888888;'>※「SEC EDGAR」リンクから、対象企業の直近の8-K（重大事態・ファイナンス）や10-Q（決算書）を直接確認できます。AI投資判断にホバーすると、投機的リスクを含む詳細考察が表示されます。</small>", unsafe_allow_html=True)

# 表示用にデータフレームを整形
df_display = df_filtered_screener.copy()
df_display["Certainty (%)"] = df_display["Certainty (%)"].map(lambda x: f"{x:.1f}%")
df_display["Total Buy Value"] = df_display["total_value"].map(lambda x: f"${x:,.0f}")
df_display["Avg Buy Price"] = df_display["avg_price"].map(lambda x: f"${x:,.2f}")
df_display["Last Trade Date"] = df_display["buy_date"].dt.strftime('%Y-%m-%d')

# 列の並び替えと選択
df_display = df_display[[
    "ticker", 
    "company", 
    "Certainty (%)", 
    "AI Status", 
    "Risk Status",
    "AI Analysis (投資考察)", 
    "Total Buy Value", 
    "Avg Buy Price", 
    "trade_count",
    "sector",
    "Last Trade Date",
    "SEC EDGAR",
    "Yahoo Finance"
]]

# 列名の日本語化
df_display.columns = [
    "Ticker", 
    "企業名", 
    "AI確実性", 
    "AI投資判断", 
    "リスク評価",
    "AI投資考察メッセージ", 
    "直近買い総額", 
    "平均取得単価", 
    "取引件数",
    "セクター",
    "最終取引日",
    "SEC EDGAR",
    "Yahoo Finance"
]

# Streamlitのインタラクティブデータテーブルで表示
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
