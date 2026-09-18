import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# ページ設定（米国証券アプリ風のワイドレイアウトとダークテーマ調のクリーンな設定）
st.set_page_config(
    page_title="US Insider Big-Whale Tracker",
    page_icon="🐋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# データベース接続関数
def load_data():
    conn = sqlite3.connect("insider.db")
    query = """
        SELECT 
            filing_date as "Filing Date",
            insider as "Insider Name",
            position as "Position",
            ticker as "Ticker",
            company as "Company Name",
            avg_price as "Avg Price ($)",
            buy_date as "Trade Date",
            total_shares as "Shares",
            total_value as "Total Value ($)",
            filing_url as "SEC Link"
        FROM insider_trades
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # 型変換と日付処理
    df["Filing Date"] = pd.to_datetime(df["Filing Date"])
    df["Trade Date"] = pd.to_datetime(df["Trade Date"])
    df["Total Value ($)"] = pd.to_numeric(df["Total Value ($)"])
    df["Avg Price ($)"] = pd.to_numeric(df["Avg Price ($)"])
    df["Shares"] = pd.to_numeric(df["Shares"])
    return df

# データの読み込み
try:
    df_raw = load_data()
except Exception as e:
    st.error(f"データベースの読み込みに失敗しました。`insider.db` がリポジトリに存在するか確認してください。 Error: {e}")
    st.stop()

# ==============================================================================
# SIDEBAR: TradingView風 高機能フィルタースクリーナー
# ==============================================================================
st.sidebar.header("🔍 Screener Filters")
st.sidebar.markdown("---")

# 1. ティッカー検索 (複数選択可)
all_tickers = sorted(df_raw["Ticker"].dropna().unique())
selected_tickers = st.sidebar.multiselect(
    "Ticker Symbol",
    options=all_tickers,
    placeholder="Search & Select Ticker(s)..."
)

# 2. 取引規模（金額）スライダー
min_val = float(df_raw["Total Value ($)"].min())
max_val = float(df_raw["Total Value ($)"].max())
selected_min_value = st.sidebar.slider(
    "Minimum Trade Value ($)",
    min_value=100000, # デフォルト最低10万ドル
    max_value=10000000, # 1000万ドル
    value=100000,
    step=50000,
    format="$%,d"
)

# 3. 役職（Position）フィルター
all_positions = sorted(df_raw["Position"].dropna().unique())
selected_positions = st.sidebar.multiselect(
    "Insider Position",
    options=all_positions,
    placeholder="All Positions"
)

# 4. 日付範囲フィルター
min_date = df_raw["Filing Date"].min().to_pydatetime()
max_date = df_raw["Filing Date"].max().to_pydatetime()
selected_date_range = st.sidebar.date_input(
    "Filing Date Range",
    value=(max_date - timedelta(days=30), max_date),
    min_value=min_date,
    max_value=max_date
)

# フィルタリング処理
df_filtered = df_raw.copy()

if selected_tickers:
    df_filtered = df_filtered[df_filtered["Ticker"].isin(selected_tickers)]

df_filtered = df_filtered[df_filtered["Total Value ($)"] >= selected_min_value]

if selected_positions:
    df_filtered = df_filtered[df_filtered["Position"].isin(selected_positions)]

if len(selected_date_range) == 2:
    start_date, end_date = selected_date_range
    df_filtered = df_filtered[
        (df_filtered["Filing Date"] >= pd.to_datetime(start_date)) & 
        (df_filtered["Filing Date"] <= pd.to_datetime(end_date))
    ]

# ==============================================================================
# MAIN DASHBOARD SCREEN
# ==============================================================================

# ヘッダーエリア
st.title("🐋 US Insider Big-Whale Tracker")
st.subheader("大口インサイダー取引（Form 4）リアルタイム分析ダッシュボード")
st.markdown(
    f"最終データ更新日: `{max_date.strftime('%Y-%m-%d')}` | "
    f"現在表示中のデータ期間: `{selected_date_range[0].strftime('%Y-%m-%d')}` 〜 `{selected_date_range[1].strftime('%Y-%m-%d') if len(selected_date_range)==2 else ''}`"
)
st.markdown("---")

# ------------------------------------------------------------------------------
# 1. MARKET OVERVIEW (サマリーカード)
# ------------------------------------------------------------------------------
total_trades_count = len(df_filtered)
total_volume_usd = df_filtered["Total Value ($)"].sum()

if not df_filtered.empty:
    max_trade_row = df_filtered.loc[df_filtered["Total Value ($)"].idxmax()]
    top_buyer_ticker = df_filtered.groupby("Ticker")["Total Value ($)"].sum().idxmax()
    top_buyer_value = df_filtered.groupby("Ticker")["Total Value ($)"].sum().max()
else:
    max_trade_row = None
    top_buyer_ticker = "N/A"
    top_buyer_value = 0

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Total Insider Buying Volume",
        value=f"${total_volume_usd:,.0f}",
        delta=f"{total_trades_count} Trades"
    )

with col2:
    st.metric(
        label="Top Buying Ticker (Aggregate)",
        value=top_buyer_ticker,
        delta=f"${top_buyer_value:,.0f} Total" if top_buyer_value > 0 else None
    )

with col3:
    if max_trade_row is not None:
        st.metric(
            label="Largest Single Trade",
            value=f"{max_trade_row['Ticker']}",
            delta=f"${max_trade_row['Total Value ($)']:,.0f} by {max_trade_row['Insider Name'][:15]}..."
        )
    else:
        st.metric(label="Largest Single Trade", value="N/A")

with col4:
    active_companies = df_filtered["Ticker"].nunique()
    st.metric(
        label="Tracked Active Companies",
        value=f"{active_companies} Companies",
        delta="Filtered Market"
    )

st.markdown("---")

# ------------------------------------------------------------------------------
# 2. VISUAL CHARTS (ビジュアル分析エリア)
# ------------------------------------------------------------------------------
chart_col1, chart_col2 = st.columns([1, 1])

with chart_col1:
    st.subheader("🔥 Top 15 Tickers by Buying Volume")
    if not df_filtered.empty:
        ticker_summary = df_filtered.groupby("Ticker")["Total Value ($)"].sum().reset_index()
        ticker_summary = ticker_summary.sort_values(by="Total Value ($)", ascending=False).head(15)
        
        fig = px.bar(
            ticker_summary,
            x="Total Value ($)",
            y="Ticker",
            orientation='h',
            color="Total Value ($)",
            color_continuous_scale="Viridis",
            labels={"Total Value ($)": "Total Value ($)", "Ticker": "Ticker"},
            template="plotly_dark"
        )
        fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=400, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("該当するデータがありません。フィルターを緩めてください。")

with chart_col2:
    st.subheader("📅 Daily Buying Trend")
    if not df_filtered.empty:
        daily_summary = df_filtered.groupby("Filing Date")["Total Value ($)"].sum().reset_index()
        
        fig_line = px.line(
            daily_summary,
            x="Filing Date",
            y="Total Value ($)",
            markers=True,
            labels={"Total Value ($)": "Daily Volume ($)", "Filing Date": "Filing Date"},
            template="plotly_dark"
        )
        fig_line.update_traces(line_color="#00FFCC", line_width=2)
        fig_line.update_layout(height=400, margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("該当するデータがありません。")

st.markdown("---")

# ------------------------------------------------------------------------------
# 3. INSIDER ACTIVITY FEED (取引履歴フィード)
# ------------------------------------------------------------------------------
st.subheader("📋 Insider Activity Feed")

if not df_filtered.empty:
    # テーブル表示用にデータを整理
    df_display = df_filtered.copy()
    
    # 日付を文字列フォーマットに
    df_display["Filing Date"] = df_display["Filing Date"].dt.strftime('%Y-%m-%d')
    df_display["Trade Date"] = df_display["Trade Date"].dt.strftime('%Y-%m-%d')
    
    # 金額のフォーマット適用
    df_display["Total Value ($)"] = df_display["Total Value ($)"].map(lambda x: f"${x:,.2f}")
    df_display["Avg Price ($)"] = df_display["Avg Price ($)"].map(lambda x: f"${x:,.2f}")
    df_display["Shares"] = df_display["Shares"].map(lambda x: f"{x:,.0f}")
    
    # 最新の開示日順にソート
    df_display = df_display.sort_values(by="Filing Date", ascending=False)

    # Streamlitのデータフレーム（リンクを有効化）
    st.dataframe(
        df_display,
        column_config={
            "SEC Link": st.column_config.LinkColumn(
                "SEC Source", 
                help="Click to view original SEC Form 4 filing",
                display_text="View Form 4"
            )
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("条件に一致するインサイダー取引履歴はありません。")
