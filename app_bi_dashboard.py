import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from datetime import datetime, timedelta

# ページ設定 (ワイドモード、ダークテーマ)
st.set_page_config(page_title="Insider Trading Workstation Pro", layout="wide")

DB_PATH = "insider.db"

# 🚀 セクターごとの固定カラー定義
SECTOR_COLORS = {
    'Technology': '#00E5FF', 'Financial Services': '#2962FF', 'Healthcare': '#00E676',
    'Consumer Defensive': '#FFB300', 'Consumer Cyclical': '#FF9100', 'Industrials': '#D500F9',
    'Energy': '#FF1744', 'Basic Materials': '#76FF03', 'Real Estate': '#00B0FF',
    'Utilities': '#AEEA00', 'Communication Services': '#F50057', 'Other': '#8b949e'
}

# 🚀 【モバイル・タブレット対応】グレー背景とレスポンシブを最適化したCSS
st.markdown("""
    <style>
    /* 全体の背景色を深みのあるダークグレーに固定 */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #0d1117 !important;
        color: #c9d1d9 !important;
    }
    
    /* テキストカラーの視認性確保 */
    html, body, [data-testid="stWidgetLabel"], .stMarkdown, p, h1, h2, h3, h4, h5, h6, span, label {
        color: #e6edf3 !important;
    }
    
    strong {
        color: #ffffff !important;
    }
    
    /* スライサーエリアの背景 */
    .slicer-container {
        background-color: #161b22 !important;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #30363d;
        margin-bottom: 15px;
    }
    
    /* 外部リンクボタン */
    .source-link {
        display: inline-block;
        padding: 4px 8px;
        background-color: #21262d;
        color: #58a6ff !important;
        border: 1px solid #30363d;
        border-radius: 4px;
        text-decoration: none;
        font-size: 11px;
        font-weight: bold;
    }
    .source-link:hover {
        background-color: #1f6feb;
        color: white !important;
        border-color: #58a6ff;
    }
    </style>
""", unsafe_allow_html=True)

# 1. データの読み込み & クレンジング (キャッシュを強力に適用してスマホでの表示を高速化)
@st.cache_data(ttl=300) # 5分間キャッシュ
def load_insider_data():
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT filing_date, insider, position, ticker, company, avg_price, buy_date, total_shares, total_value, filing_url
        FROM insider_trades
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df['total_value'] = pd.to_numeric(df['total_value'], errors='coerce')
    df['avg_price'] = pd.to_numeric(df['avg_price'], errors='coerce')
    df['total_shares'] = pd.to_numeric(df['total_shares'], errors='coerce')
    df['buy_date'] = pd.to_datetime(df['buy_date'], errors='coerce')
    
    df['ticker'] = df['ticker'].astype(str).str.strip().str.upper()
    df = df[(df['total_value'] > 0) & (df['avg_price'] < 5000)]
    return df

# 最新株価と過去株価を一括取得してリターンを高速計算する関数（API制限・遅延対策）
@st.cache_data(ttl=1800)
def batch_calculate_returns(tickers):
    price_data = {}
    if not tickers:
        return price_data
    try:
        # 複数銘柄の過去6ヶ月分のデータを一括ダウンロード (並列処理)
        data = yf.download(tickers, period="6m", group_by='ticker', progress=False, threads=True)
        for t in tickers:
            try:
                if len(tickers) == 1:
                    df_t = data
                else:
                    df_t = data[t]
                
                df_t = df_t.dropna(subset=['Close'])
                if not df_t.empty:
                    current = df_t['Close'].iloc[-1]
                    p_1m = df_t['Close'].iloc[-20] if len(df_t) >= 20 else df_t['Close'].iloc[0]
                    p_3m = df_t['Close'].iloc[-60] if len(df_t) >= 60 else df_t['Close'].iloc[0]
                    p_6m = df_t['Close'].iloc[-120] if len(df_t) >= 120 else df_t['Close'].iloc[0]
                    
                    price_data[t] = {
                        'current_price': current,
                        '1M_Ret': f"{((current / p_1m) - 1) * 100:+.1f}%",
                        '3M_Ret': f"{((current / p_3m) - 1) * 100:+.1f}%",
                        '6M_Ret': f"{((current / p_6m) - 1) * 100:+.1f}%"
                    }
            except:
                pass
    except:
        pass
    return price_data

try:
    df_raw = load_insider_data()
except Exception as e:
    st.error(f"データベースの読み込みに失敗しました。: {e}")
    st.stop()

# セクター情報の一括マッピング
@st.cache_data(ttl=3600)
def get_sector_info(tickers):
    # API負荷を避けるため、上位50件に制限
    return {t: yf.Ticker(t).info.get('sector', 'Financial Services') for t in tickers[:50]}

unique_tickers = df_raw['ticker'].unique().tolist()
sector_map = get_sector_info(unique_tickers)
df_raw['sector'] = df_raw['ticker'].map(sector_map).fillna('Other')

# --- 🚀 セッション状態管理 🚀 ---
if 'selected_ticker' not in st.session_state:
    st.session_state.selected_ticker = "RSG" if "RSG" in df_raw['ticker'].values else df_raw['ticker'].iloc[0]

# ==============================================================================
# 🎛️ 1. 上部セクター・スライサー
# ==============================================================================
st.markdown('<div class="slicer-container">', unsafe_allow_html=True)
st.subheader("🔍 セクター・スライサー")
selected_sectors = st.multiselect(
    "表示するセクターを選択してください（複数選択可能）",
    options=sorted(df_raw['sector'].unique()),
    default=sorted(df_raw['sector'].unique())
)
st.markdown('</div>', unsafe_allow_html=True)

# データのフィルタリング適用
df_filtered = df_raw[df_raw['sector'].isin(selected_sectors)]

# ==============================================================================
# 📊 2. 中段：高密度マトリックス・テーブル
# ==============================================================================
st.subheader("📋 スライサー連動・高密度銘柄マトリックス")

# 銘柄ごとの集計
ticker_summary = df_filtered.groupby('ticker').agg({
    'total_value': 'sum',
    'insider': 'count',
    'sector': 'first',
    'filing_url': 'first'
}).rename(columns={'insider': 'trades_count'}).reset_index()

ticker_summary = ticker_summary.sort_values(by='total_value', ascending=False).head(20).reset_index(drop=True)

if not ticker_summary.empty:
    # 期間別リターンを一括計算してテーブルにマージ
    batch_prices = batch_calculate_returns(ticker_summary['ticker'].tolist())
    ticker_summary['1M リターン'] = ticker_summary['ticker'].map(lambda x: batch_prices.get(x, {}).get('1M_Ret', 'N/A'))
    ticker_summary['3M リターン'] = ticker_summary['ticker'].map(lambda x: batch_prices.get(x, {}).get('3M_Ret', 'N/A'))
    ticker_summary['6M リターン'] = ticker_summary['ticker'].map(lambda x: batch_prices.get(x, {}).get('6M_Ret', 'N/A'))
    
    # 高密度インタラクティブテーブル
    selected_row = st.dataframe(
        ticker_summary.style.format({'total_value': '${:,.0f}'}),
        use_container_width=True,
        height=240, # スマホでもスクロールしやすくするためコンパクトに設定
        column_config={
            "ticker": "銘柄コード",
            "total_value": "総買い額",
            "trades_count": "取引件数",
            "sector": "セクター",
            "1M リターン": "1M",
            "3M リターン": "3M",
            "6M リターン": "6M",
            "filing_url": st.column_config.LinkColumn("Edgar")
        },
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # 行選択時の連動処理
    if selected_row and len(selected_row.selection.rows) > 0:
        selected_idx = selected_row.selection.rows[0]
        st.session_state.selected_ticker = ticker_summary.iloc[selected_idx]['ticker']

# ==============================================================================
# 📈 3. 下部：選択された銘柄のリアルタイムチャート & 詳細分析
# ==============================================================================
st.markdown("---")
current_ticker = st.session_state.selected_ticker
ticker_trades = df_raw[df_raw['ticker'] == current_ticker].sort_values(by='buy_date')

if not ticker_trades.empty:
    current_sector = ticker_trades['sector'].iloc[0]
    current_color = SECTOR_COLORS.get(current_sector, '#8b949e')
    company_name = ticker_trades['company'].iloc[0]
    
    st.subheader(f"📈 {current_ticker} のリアルタイム分析")
    
    # 外部ソースリンク (モバイルで押しやすいようにボタン化)
    st.markdown(f"""
        <div style="margin-bottom: 15px;">
            <a class="source-link" href="https://finviz.com/quote.ashx?t={current_ticker}" target="_blank">📊 Finviz</a>
            <a class="source-link" href="https://www.tradingview.com/symbols/{current_ticker}/" target="_blank">📈 TradingView</a>
            <span style="float: right; padding: 4px 10px; border-radius: 20px; background-color: {current_color}22; color: {current_color}; border: 1px solid {current_color}; font-size: 11px; font-weight: bold;">
                {current_sector}
            </span>
        </div>
    """, unsafe_allow_html=True)
    
    # メタ情報ダッシュボード
    top_insider_row = ticker_trades.groupby(['insider', 'position'])['total_value'].sum().idxmax()
    st.markdown(f"""
        <div style="background-color: #161b22; padding: 12px; border-radius: 8px; border: 1px solid #30363d; margin-bottom: 15px;">
            <span style="color: #8b949e; font-size: 11px; font-weight: bold;">🏢 企業名:</span> 
            <strong style="color: #FFFFFF; font-size: 13px; margin-right: 15px;">{company_name}</strong><br>
            <span style="color: #8b949e; font-size: 11px; font-weight: bold;">👑 トップ買い手:</span> 
            <strong style="color: #00E676; font-size: 13px;">{top_insider_row[0]} ({top_insider_row[1]})</strong> 
        </div>
    """, unsafe_allow_html=True)

    # 主要KPIメトリクス
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("累計購入総額", f"${ticker_trades['total_value'].sum():,.0f}")
    with m2: st.metric("累計取引件数", f"{len(ticker_trades)} 件")
    with m3: st.metric("総取得株数", f"{ticker_trades['total_shares'].sum():,.0f} 株")
    with m4: st.metric("平均取得単価", f"${ticker_trades['avg_price'].mean():,.2f}")
    
    # チャートコントロール
    cc1, cc2, cc3 = st.columns(3)
    with cc1: chart_style = st.radio("表示形式", ["ローソク足", "折れ線"], key="style_radio_work", horizontal=True)
    with cc2: show_bb = st.checkbox("ボリンジャーバンドを表示", value=True, key="bb_chk_work")
    with cc3: show_rsi = st.checkbox("RSI (14) を表示", value=True, key="rsi_chk_work")

    # 株価取得とチャート描画
    try:
        stock_df = yf.download(current_ticker, start=(datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'), progress=False)
        if not stock_df.empty:
            close_prices = stock_df['Close'].squeeze()
            
            # テクニカル計算
            ma20 = close_prices.rolling(window=20).mean()
            std20 = close_prices.rolling(window=20).std()
            upper_band = ma20 + (std20 * 2)
            lower_band = ma20 - (std20 * 2)
            
            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rsi = 100 - (100 / (1 + (gain / loss)))
            
            fig = make_subplots(rows=2 if show_rsi else 1, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.78, 0.22] if show_rsi else [1.0])
            
            # ボリンジャーバンド (深みのあるネオングリーン)
            if show_bb:
                x_bb = list(stock_df.index) + list(stock_df.index)[::-1]
                y_bb = list(upper_band) + list(lower_band)[::-1]
                fig.add_trace(go.Scatter(
                    x=x_bb, y=y_bb, fill='toself',
                    fillcolor='rgba(0, 230, 118, 0.05)',
                    line=dict(color='rgba(0, 230, 118, 0.25)', width=1),
                    name="ボリンジャーバンド", hoverinfo='skip'
                ), row=1, col=1)
                fig.add_trace(go.Scatter(x=stock_df.index, y=ma20, line=dict(color="#FFB300", width=1, dash="dash"), name="20日移動平均"), row=1, col=1)
            
            # メイン株価
            if chart_style == "ローソク足":
                fig.add_trace(go.Candlestick(
                    x=stock_df.index, open=stock_df['Open'].squeeze(), high=stock_df['High'].squeeze(), low=stock_df['Low'].squeeze(), close=close_prices,
                    name="株価", increasing_line_color='#00E676', decreasing_line_color='#FF1744'
                ), row=1, col=1)
            else:
                fig.add_trace(go.Scatter(x=stock_df.index, y=close_prices, name="株価", line=dict(color="#2962FF", width=2)), row=1, col=1)
                
            # インサイダー取引プロット
            visible_trades = ticker_trades[ticker_trades['buy_date'] >= stock_df.index.min()].copy()
            if not visible_trades.empty:
                vals = visible_trades['total_value'].values
                log_vals = np.log10(vals + 1)
                min_log, max_log = log_vals.min(), log_vals.max()
                sizes = 12 + 18 * (log_vals - min_log) / (max_log - min_log) if max_log != min_log else np.full_like(log_vals, 15)
                
                fig.add_trace(go.Scatter(
                    x=visible_trades['buy_date'], y=visible_trades['avg_price'], mode='markers', name='インサイダー買い',
                    marker=dict(color='#D500F9', size=sizes, symbol='triangle-up', line=dict(color='#FFFFFF', width=1.5)),
                    text=[f"役職: {pos}<br>購入者: {name}<br>金額: ${val:,.0f}" for pos, name, val in zip(visible_trades['position'], visible_trades['insider'], visible_trades['total_value'])],
                    hoverinfo='text'
                ), row=1, col=1)
                
            # RSI
            if show_rsi:
                fig.add_trace(go.Scatter(x=stock_df.index, y=rsi, name="RSI(14)", line=dict(color="#FF9100", width=1.5)), row=2, col=1)
                fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 23, 68, 0.4)", row=2, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 230, 118, 0.4)", row=2, col=1)

            # レイアウト調整 (スマホでも見やすい高さに調整)
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="#0d1117", paper_bgcolor="#161b22",
                height=400, xaxis_rangeslider_visible=False, margin=dict(l=40, r=10, t=10, b=10),
                font=dict(color="#E0E3EB", family="Arial, sans-serif"),
                legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center", font=dict(color="#E0E3EB", size=10), bgcolor="rgba(0,0,0,0)")
            )
            fig.update_xaxes(tickfont=dict(color="#E0E3EB"), gridcolor="#21262d")
            fig.update_yaxes(tickfont=dict(color="#E0E3EB"), gridcolor="#21262d")
            
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.warning("株価データを取得できませんでした。")
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
