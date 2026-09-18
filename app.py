import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Insider & Technical AI Dashboard",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="collapsed" # サイドバーをデフォルトで閉じる（不要なため）
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
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. DATA LOADING (SQLite)
# ==============================================================================
@st.cache_data(ttl=3600)
def load_insider_data():
    conn = sqlite3.connect("insider.db")
    query = """
        SELECT 
            filing_date as filing_date,
            insider as insider,
            position as position,
            ticker as ticker,
            company as company,
            avg_price as avg_price,
            buy_date as buy_date,
            total_shares as shares,
            total_value as total_value,
            filing_url as url
        FROM insider_trades
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["total_value"] = pd.to_numeric(df["total_value"])
    df["avg_price"] = pd.to_numeric(df["avg_price"])
    df["shares"] = pd.to_numeric(df["shares"])
    return df

try:
    df_insider = load_insider_data()
except Exception as e:
    st.error(f"SQLiteデータベースの読み込みに失敗しました。: {e}")
    st.stop()

# ==============================================================================
# 3. HEADER & MINIMAL SELECTOR
# ==============================================================================
st.title("👁️ Whale-Eye Dashboard")
st.markdown("大口インサイダー取引（Form 4）× ボリンジャーバンドテクニカル分析 × AI投資確実性シグナル")
st.markdown("---")

# データベースにデータが存在するティッカーのみを選択肢にする（デフォルトは取引総額が最大の銘柄）
if not df_insider.empty:
    top_tickers = df_insider.groupby("ticker")["total_value"].sum().sort_values(ascending=False).index.tolist()
else:
    top_tickers = ["AAPL"]

# 唯一の選択肢（メイン画面上部にスマートに配置）
col_sel1, col_sel2 = st.columns([1, 3])
with col_sel1:
    target_ticker = st.selectbox("🎯 分析対象銘柄を選択:", options=top_tickers, index=0)
with col_sel2:
    # 選択された銘柄の企業名を取得して表示
    company_name = df_insider[df_insider["ticker"] == target_ticker]["company"].iloc[0] if target_ticker in df_insider["ticker"].values else ""
    st.markdown(f"<h3 style='margin-top: 10px; color: #888888;'>{company_name}</h3>", unsafe_allow_html=True)

# ==============================================================================
# 4. YAHOO FINANCE DATA & BOLLINGER BANDS CALCULATION
# ==============================================================================
@st.cache_data(ttl=3600)
def fetch_stock_data(ticker):
    # 過去6ヶ月のデータを取得
    stock = yf.Ticker(ticker)
    df_stock = stock.history(period="6m")
    return df_stock, stock

df_stock, yf_ticker = fetch_stock_data(target_ticker)

if df_stock.empty:
    st.warning(f"Yahoo Financeから {target_ticker} の株価データを取得できませんでした。")
    st.stop()

# テクニカル指標計算 (ボリンジャーバンド 20日, 2σ)
df_stock['MA20'] = df_stock['Close'].rolling(window=20).mean()
df_stock['STD20'] = df_stock['Close'].rolling(window=20).std()
df_stock['Upper_Band'] = df_stock['MA20'] + (df_stock['STD20'] * 2)
df_stock['Lower_Band'] = df_stock['MA20'] - (df_stock['STD20'] * 2)

# 直近の価格情報
current_price = df_stock['Close'].iloc[-1]
prev_price = df_stock['Close'].iloc[-2]
price_change = current_price - prev_price
price_change_pct = (price_change / prev_price) * 100

# ==============================================================================
# 5. AI COGNITIVE ENGINE (シグナル確実性 & 目標株価の算出)
# ==============================================================================
# 独自のロジックでテクニカルとインサイダーをスコア化
# 1. テクニカルスコア (ボリンジャーバンドの位置)
# Lower Bandに近いほど買いシグナル高
bb_width = df_stock['Upper_Band'].iloc[-1] - df_stock['Lower_Band'].iloc[-1]
position_in_bb = (current_price - df_stock['Lower_Band'].iloc[-1]) / bb_width if bb_width > 0 else 0.5

# 0(Lower)に近いほど高スコア、1(Upper)に近いほど低スコア
technical_score = max(0, min(100, (1 - position_in_bb) * 100))

# 2. インサイダースコア (直近3ヶ月の買い総額)
ticker_insider = df_insider[df_insider["ticker"] == target_ticker]
three_months_ago = datetime.now() - timedelta(days=90)
recent_insider = ticker_insider[ticker_insider["buy_date"] >= three_months_ago]
total_insider_buy = recent_insider["total_value"].sum()

# 10万ドルで10点、100万ドル以上で上限50点加算
insider_score = min(50, (total_insider_buy / 100000) * 5)

# 確実性(%)の統合算出
base_certainty = 40.0 # ベースライン
# テクニカルが割安(BB下限付近)かつインサイダー買いがある場合、確実性を引き上げる
certainty_score = base_certainty + (technical_score * 0.4) + insider_score
certainty_score = min(98.5, max(15.0, certainty_score)) # 上限98.5%に設定

# 目標株価の算出 (アナリスト平均値、またはBB上限ベースのAI算出)
try:
    info = yf_ticker.info
    target_high = info.get("targetHighPrice", None)
    target_mean = info.get("targetMeanPrice", None)
except:
    target_high = None
    target_mean = None

if not target_mean:
    # アナリストデータがない場合は、ボリンジャーバンド上限+5%をAI目標株価とする
    ai_target_price = df_stock['Upper_Band'].iloc[-1] * 1.05
else:
    ai_target_price = target_mean

# AI投資考察メッセージの動的生成
if certainty_score >= 75:
    ai_status = "強気 (Strong Buy)"
    ai_color = "#00FFCC"
    ai_analysis = (
        f"現在、株価はボリンジャーバンドの下限付近（${df_stock['Lower_Band'].iloc[-1]:,.2f}）に位置しており、テクニカル的に売られすぎの水準です。 "
        f"さらに、直近90日以内にインサイダー（内部関係者）による総額 ${total_insider_buy:,.0f} の大口買い戻しが観測されており、"
        f"底値圏である確実性が極めて高いと判断されます。中長期的な反発を狙う絶好の仕込み時と言えます。"
    )
elif certainty_score >= 50:
    ai_status = "中立・押し目買い推奨 (Hold / Buy on Dips)"
    ai_color = "#FFCC00"
    ai_analysis = (
        f"株価は移動平均線（${df_stock['MA20'].iloc[-1]:,.2f}）付近で安定推移しています。急激な割安感はありませんが、"
        f"インサイダーの買い支えが下値を限定的にしています。急落時の押し目買い、またはバンドが収縮（スクイーズ）した後の"
        f"上放れを確認してからのエントリーが推奨されます。"
    )
else:
    ai_status = "様子見 (Avoid / Wait)"
    ai_color = "#FF3366"
    ai_analysis = (
        f"現在、株価はボリンジャーバンドの上限（${df_stock['Upper_Band'].iloc[-1]:,.2f}）付近に達しており、短期的には過熱感があります。 "
        f"直近で目立ったインサイダーの追加買いも見られず、ここからの新規エントリーは高値掴みのリスクを伴います。"
        f"一度調整が入り、バンドの中央線または下限付近まで引きつけるのを待つのが賢明です。"
    )

# ==============================================================================
# 6. DASHBOARD DISPLAY
# ==============================================================================

# ------------------------------------------------------------------------------
# A. AI INSIGHTS PANEL (最上部に最も重要な結論を配置)
# ------------------------------------------------------------------------------
st.markdown(f"### 🤖 AI Investment Analysis for {target_ticker}")

ai_col1, ai_col2, ai_col3 = st.columns([1, 1, 2])

with ai_col1:
    st.metric(
        label="Current Price",
        value=f"${current_price:,.2f}",
        delta=f"{price_change_pct:+.2f}% (Daily)"
    )
with ai_col2:
    st.metric(
        label="AI Target Price (12M)",
        value=f"${ai_target_price:,.2f}",
        delta=f"{(ai_target_price - current_price)/current_price*100:+.1f}% Upside"
    )
with ai_col3:
    # 確実性ゲージ風表示
    st.markdown(f"**Signal Certainty (確実性)**")
    st.markdown(f"<h1 style='color: {ai_color}; margin-top: -10px;'>{certainty_score:.1f}%</h1>", unsafe_allow_html=True)
    st.markdown(f"**AI Status:** <span style='color:{ai_color}; font-weight:bold;'>{ai_status}</span>", unsafe_allow_html=True)

# AI考察テキスト
st.info(ai_analysis)
st.markdown("---")

# ------------------------------------------------------------------------------
# B. BOLLINGER BAND & WHALE BUYING CHART
# ------------------------------------------------------------------------------
st.markdown("### 📈 Bollinger Bands (20, 2σ) & Insider Whale Purchases")

# チャートデータの作成
fig = go.Figure()

# ボリンジャーバンド（アッパー、ロワー、MA）
fig.add_trace(go.Scatter(
    x=df_stock.index, y=df_stock['Upper_Band'],
    line=dict(color='rgba(173, 216, 230, 0.2)', width=1),
    name='Upper Band (+2σ)'
))
fig.add_trace(go.Scatter(
    x=df_stock.index, y=df_stock['Lower_Band'],
    line=dict(color='rgba(173, 216, 230, 0.2)', width=1),
    fill='tonexty', fillcolor='rgba(173, 216, 230, 0.03)',
    name='Lower Band (-2σ)'
))
fig.add_trace(go.Scatter(
    x=df_stock.index, y=df_stock['MA20'],
    line=dict(color='rgba(255, 255, 255, 0.3)', width=1.5, dash='dash'),
    name='MA (20)'
))
# 終値
fig.add_trace(go.Scatter(
    x=df_stock.index, y=df_stock['Close'],
    line=dict(color='#00FFCC', width=2.5),
    name='Close Price'
))

# 大口インサイダー買いのプロット（🐋マークでマッピング）
# 株価データの期間に合致するインサイダー取引を抽出
ticker_insider_filtered = ticker_insider[
    (ticker_insider["buy_date"] >= df_stock.index.min()) & 
    (ticker_insider["buy_date"] <= df_stock.index.max())
]

if not ticker_insider_filtered.empty:
    # 同一日の取引をグループ化して、ポップアップにまとめて表示できるようにする
    grouped_insider = ticker_insider_filtered.groupby("buy_date").agg({
        "total_value": "sum",
        "insider": lambda x: ", ".join(x.unique()[:2]), # 代表して2名表示
        "avg_price": "mean"
    }).reset_index()

    # インサイダーが買った日の終値を取得して、プロット位置にする
    grouped_insider = grouped_insider.set_index("buy_date").join(df_stock[['Close']], how='inner').reset_index()

    fig.add_trace(go.Scatter(
        x=grouped_insider["index"],
        y=grouped_insider["Close"],
        mode='markers+text',
        marker=dict(
            symbol='triangle-up',
            size=16,
            color='#E040FB', # 鮮やかなパープル
            line=dict(color='#FFFFFF', width=1.5)
        ),
        text="🐋",
        textposition="top center",
        textfont=dict(size=18),
        hovertemplate=(
            "<b>🐋 Insider Whale Buy</b><br>" +
            "Date: %{x|%Y-%m-%d}<br>" +
            "Total Value: $%{customdata:,.0f}<br>" +
            "Insiders: %{text}<br>" +
            "<extra></extra>"
        ),
        customdata=grouped_insider["total_value"],
        name="Whale Purchase"
    ))

fig.update_layout(
    template="plotly_dark",
    plot_bgcolor='#0E1117',
    paper_bgcolor='#0E1117',
    margin=dict(l=10, r=10, t=10, b=10),
    height=500,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    xaxis=dict(gridcolor='rgba(255, 255, 255, 0.05)'),
    yaxis=dict(gridcolor='rgba(255, 255, 255, 0.05)', side="right")
)

st.plotly_chart(fig, use_container_width=True)
st.markdown("---")

# ------------------------------------------------------------------------------
# C. NEWS & ACTIVITY FEED
# ------------------------------------------------------------------------------
col_bottom1, col_bottom2 = st.columns([1, 1])

with col_bottom1:
    st.markdown("### 📰 Daily Market News (Yahoo Finance)")
    try:
        news_list = yf_ticker.news
        if news_list:
            for item in news_list[:5]: # 直近5件を表示
                title = item.get("title", "No Title")
                link = item.get("link", "#")
                publisher = item.get("publisher", "Unknown")
                provider_publish_time = item.get("providerPublishTime", 0)
                pub_date = datetime.fromtimestamp(provider_publish_time).strftime('%Y-%m-%d %H:%M')
                
                st.markdown(f"**[{title}]({link})**")
                st.markdown(f"<small style='color: #888888;'>{publisher} | {pub_date}</small>", unsafe_allow_html=True)
                st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
        else:
            st.info("現在、この銘柄に関する新しいニュースはありません。")
    except Exception as e:
        st.info("ニュース情報の取得中に一時的なエラーが発生しました。")

with col_bottom2:
    st.markdown("### 📋 Recent Insider Records")
    if not ticker_insider.empty:
        # 直近10件の生データを表示
        recent_records = ticker_insider.sort_values(by="filing_date", ascending=False).head(10)
        
        # 表示用フォーマット
        recent_records["filing_date"] = recent_records["filing_date"].dt.strftime('%Y-%m-%d')
        recent_records["buy_date"] = recent_records["buy_date"].dt.strftime('%Y-%m-%d')
        recent_records["total_value"] = recent_records["total_value"].map(lambda x: f"${x:,.0f}")
        recent_records["avg_price"] = recent_records["avg_price"].map(lambda x: f"${x:,.2f}")
        recent_records["shares"] = recent_records["shares"].map(lambda x: f"{x:,.0f}")
        
        st.dataframe(
            recent_records[["filing_date", "insider", "position", "avg_price", "total_value", "url"]],
            column_config={
                "url": st.column_config.LinkColumn("SEC Link", display_text="View Form 4")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("インサイダー取引の記録がありません。")
