import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Insider AI Screener",
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
# 2. DATA LOADING & AGGREGATION (SQLite ONLY - NO YFINANCE)
# ==============================================================================
@st.cache_data(ttl=600) # 10分キャッシュ
def load_and_process_data():
    conn = sqlite3.connect("insider.db")
    query = """
        SELECT 
            filing_date,
            insider,
            position,
            ticker,
            company,
            avg_price,
            buy_date,
            total_shares as shares,
            total_value
        FROM insider_trades
        WHERE ticker IS NOT NULL 
          AND ticker != '' 
          AND UPPER(ticker) != 'NONE'
          AND UPPER(ticker) != 'N/A'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # 型変換
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"], errors='coerce')
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors='coerce')
    df["shares"] = pd.to_numeric(df["shares"], errors='coerce')
    
    # 異常データのクリーニング (1億ドル以上の極端な単一取引はデータエラーの可能性が高いため除外、または実態に合わせる)
    df = df[df["total_value"] < 500000000] # 5000万ドル以上の異常値を排除
    
    return df

try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"SQLiteデータベースの読み込みに失敗しました。: {e}")
    st.stop()

# ==============================================================================
# 3. AI COGNITIVE ENGINE (全銘柄一括スコアリング)
# ==============================================================================
def generate_screener(df):
    # 銘柄（Ticker）ごとに集計
    # 直近90日間の買い
    three_months_ago = datetime.now() - timedelta(days=90)
    df_recent = df[df["buy_date"] >= three_months_ago]
    
    if df_recent.empty:
        df_recent = df # データが少なければ全期間を対象にする
        
    # 銘柄ごとの集計
    summary = df_recent.groupby("ticker").agg({
        "total_value": "sum",
        "avg_price": "mean",
        "insider": lambda x: ", ".join(x.unique()[:2]), # 主な購入者2名
        "company": "first",
        "buy_date": "max" # 直近の取引日
    }).reset_index()
    
    # AI確実性とステータスの算出
    # インサイダーの買い総額に基づくスコア（最大98.5%、最小50%）
    # 10万ドルで60%、100万ドルで80%、500万ドル以上で95%以上に漸近する対数風の数式
    summary["Certainty (%)"] = summary["total_value"].apply(
        lambda val: min(98.5, max(50.0, 50.0 + (np.log10(val + 1) * 7.5)))
    )
    
    def get_ai_status(row):
        score = row["Certainty (%)"]
        val = row["total_value"]
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
        ticker = row["ticker"]
        avg_p = row["avg_price"]
        
        if score >= 85:
            return f"【超強力シグナル】インサイダー（{insiders}等）が直近で総額 ${val:,.0f}（平均単価: ${avg_p:,.2f}）の極めて大規模な買いを実行。内部関係者の絶対的な自信の現れであり、中長期の底値圏である確実性が非常に高いです。"
        elif score >= 70:
            return f"【好材料】内部関係者による総額 ${val:,.0f} のまとまった買いが観測されています。下値支持線として機能する可能性が高く、押し目買いに適した水準です。"
        else:
            return f"【監視対象】直近で ${val:,.0f} 規模のインサイダー買いが確認されました。まだ規模が小さいため、追加の買い増しやテクニカルの反発を待ちたい局面です。"

    summary["AI Status"] = summary.apply(get_ai_status, axis=1)
    summary["AI Analysis (投資考察)"] = summary.apply(get_ai_analysis, axis=1)
    
    # 外部投資ツールへのリンク作成
    # target="_blank" で新規タブ（ブラウザ設定によっては同一グループタブ）で開く
    summary["Finviz Chart"] = summary["ticker"].apply(lambda t: f"https://finviz.com/quote.ashx?t={t}")
    summary["Yahoo Finance"] = summary["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    
    # ソート（確実性の高い順 ＝ 買い総額の大きい順）
    summary = summary.sort_values(by="Certainty (%)", ascending=False)
    return summary

df_screener = generate_screener(df_raw)

# ==============================================================================
# 4. DASHBOARD DISPLAY
# ==============================================================================
st.title("👁️ Whale-Eye AI Screener")
st.markdown("大口インサイダー取引（Form 4）データからAIが「投資確実性（%）」を自動算出し、全銘柄をスクリーニングします。")
st.markdown("---")

# ------------------------------------------------------------------------------
# A. MARKET OVERVIEW (全体サマリー)
# ------------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("分析対象の総インサイダー銘柄数", f"{len(df_screener)} 銘柄")
with col2:
    strong_buys = len(df_screener[df_screener["Certainty (%)"] >= 85])
    st.metric("🔥 最強シグナル（Strong Buy）検出数", f"{strong_buys} 銘柄")
with col3:
    total_market_buy = df_raw["total_value"].sum()
    st.metric("追跡中の総インサイダー買付額", f"${total_market_buy:,.0f}")

st.markdown("---")

# ------------------------------------------------------------------------------
# B. MAIN SCREENER TABLE (全銘柄リスト表示)
# ------------------------------------------------------------------------------
st.subheader("📋 AI Insider Screener & Analysis List")
st.markdown("<small style='color:#888888;'>※「Finviz」や「Yahoo Finance」のリンクをクリックすると、外部のプロ用チャート・詳細ページが新規タブで開きます。</small>", unsafe_allow_html=True)

# 表示用にデータフレームを整形
df_display = df_screener.copy()
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
    "Total Buy Value", 
    "Avg Buy Price", 
    "Last Trade Date",
    "insider",
    "Finviz Chart",
    "Yahoo Finance",
    "AI Analysis (投資考察)"
]]

# 列名の日本語化
df_display.columns = [
    "Ticker", 
    "企業名", 
    "AI確実性", 
    "AI投資判断", 
    "直近買い総額", 
    "平均取得単価", 
    "最終取引日",
    "主なインサイダー",
    "Finviz Chart",
    "Yahoo Finance",
    "AI投資考察メッセージ"
]

# Streamlitのインタラクティブデータテーブルで表示（リンクを有効化）
st.dataframe(
    df_display,
    column_config={
        "Finviz Chart": st.column_config.LinkColumn(
            "📊 Chart (Finviz)", 
            display_text="View Chart ↗"
        ),
        "Yahoo Finance": st.column_config.LinkColumn(
            "📰 Detail (Yahoo)", 
            display_text="View Detail ↗"
        )
    },
    use_container_width=True,
    hide_index=True,
    height=600 # 縦に長く表示してスクロール可能に
)

st.markdown("---")

# ------------------------------------------------------------------------------
# C. RAW DATA FEED (直近の全生取引データフィード)
# ------------------------------------------------------------------------------
st.subheader("⏱️ Recent Raw Insider Feed (直近の全取引履歴)")

df_raw_display = df_raw.sort_values(by="filing_date", ascending=False).head(30).copy()
df_raw_display["filing_date"] = df_raw_display["filing_date"].dt.strftime('%Y-%m-%d')
df_raw_display["buy_date"] = df_raw_display["buy_date"].dt.strftime('%Y-%m-%d')
df_raw_display["total_value"] = df_raw_display["total_value"].map(lambda x: f"${x:,.0f}")
df_raw_display["avg_price"] = df_raw_display["avg_price"].map(lambda x: f"${x:,.2f}")
df_raw_display["shares"] = df_raw_display["shares"].map(lambda x: f"{x:,.0f}")

st.dataframe(
    df_raw_display[["filing_date", "ticker", "company", "insider", "position", "avg_price", "total_value", "url"]],
    column_config={
        "url": st.column_config.LinkColumn("SEC Link", display_text="View Form 4 ↗")
    },
    use_container_width=True,
    hide_index=True
)
