import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as gr
from datetime import datetime, timedelta
import math

# 独自モジュールから関数をインポート
from data_loader import (
    load_and_process_data,
    generate_screener,
    fetch_market_data,
    compute_technical_indicators,
    fetch_option_chain_by_expiry,
    fetch_catalyst_events
)
from charts import (
    draw_stock_chart,
    draw_sub_indicators_chart
)

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Option and Insider Intelligence",
    page_icon="O",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.html("""
    <style>
    .stApp { background-color: #0B0F19; color: #E2E8F0; }
    div[data-testid="stMetricValue"] { font-size: 20px; font-weight: bold; color: #00FFCC !important; font-family: 'Consolas', monospace; }
    div[data-testid="stMetricLabel"] { color: #94A3B8 !important; font-size: 11px; }
    hr { border-color: #1E293B !important; }
    a { color: #00FFCC !important; text-decoration: none; font-weight: bold; }
    .strategy-card { background-color: #111827; border: 1px solid #1F2937; border-left: 5px solid #00FFCC; padding: 20px; border-radius: 8px; margin-bottom: 18px; }
    .strategy-card-secondary { background-color: #0F172A; border: 1px solid #1E293B; border-left: 5px solid #38BDF8; padding: 20px; border-radius: 8px; margin-bottom: 18px; }
    .strategy-card-warning { background-color: #1E1B4B; border: 1px solid #312E81; border-left: 5px solid #A855F7; padding: 20px; border-radius: 8px; margin-bottom: 16px; }
    .guide-panel { background-color: #0F172A; border: 1px solid #1E293B; padding: 20px; border-radius: 8px; margin-bottom: 24px; border-top: 4px solid #38BDF8; }
    div[data-testid="stRadio"] > div { gap: 12px; }
    </style>
""")

# ==============================================================================
# 2. DATA INITIALIZATION
# ==============================================================================
try:
    df_raw = load_and_process_data()
except Exception as e:
    st.error(f"Database Error: {e}")
    st.stop()

df_screener = generate_screener(df_raw)
top_10_tickers = df_screener["ticker"].head(10).tolist()
all_available_tickers = df_screener["ticker"].tolist()

# セッション状態の初期化
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = "SMMT" if "SMMT" in all_available_tickers else (top_10_tickers[0] if top_10_tickers else "")
    
# 検索履歴（動的に追加されたカスタム銘柄）を保持するリスト
if "custom_tickers" not in st.session_state:
    st.session_state.custom_tickers = []

# ==============================================================================
# 3. MAIN TERMINAL LAYOUT
# ==============================================================================
st.title("Whale-Eye: Institutional Option and Insider Intelligence")
st.markdown("---")

st.subheader("[Screener] All Tickers Multi-Dimensional Screening Matrix")
col_sel1, col_sel2 = st.columns([4, 8])

with col_sel1:
    # データベースから取得した全銘柄リストに、ユーザーが過去に検索したカスタム銘柄を結合
    search_options = all_available_tickers.copy()
    for ct in st.session_state.custom_tickers:
        if ct not in search_options:
            search_options.append(ct)
            
    # 現在選択されているティッカーが選択肢にない場合は、選択肢に追加
    if st.session_state.selected_ticker not in search_options:
        search_options.append(st.session_state.selected_ticker)

    # 以前の美しいドロップダウン（検索機能付き）を復元
    selected_from_dropdown = st.selectbox(
        "Search / Select Ticker (Direct input allowed for new tickers):",
        options=search_options,
        index=search_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in search_options else 0
    )
    
    if selected_from_dropdown != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_from_dropdown
        st.rerun()

with col_sel2:
    # クイック選択ラジオボタン
    radio_options = list(top_10_tickers)
    if st.session_state.selected_ticker not in radio_options:
        radio_options.append(st.session_state.selected_ticker)
    selected_by_radio = st.radio(
        "Quick Selection:",
        options=radio_options,
        index=radio_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in radio_options else 0,
        horizontal=True,
        key="ticker_radio"
    )
    if selected_by_radio != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_by_radio
        st.rerun()

current_ticker = st.session_state.selected_ticker

# スクリーナー表示
df_screener_display = df_screener.copy()
df_screener_display = df_screener_display.rename(columns={
    "ticker": "Ticker", "company": "Company Name", "total_value": "Total Value ($)",
    "avg_price": "Avg Buy Price ($)", "insider": "Key Insider", "buy_date": "Trade Date",
    "trade_count": "Trades", "Certainty (%)": "Certainty Score (%)"
})
df_screener_display["Total Value ($)"] = df_screener_display["Total Value ($)"].map(lambda x: f"${x:,.0f}")
df_screener_display["Avg Buy Price ($)"] = df_screener_display["Avg Buy Price ($)"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
df_screener_display["Trade Date"] = df_screener_display["Trade Date"].dt.strftime('%Y-%m-%d')
df_screener_display["Certainty Score (%)"] = df_screener_display["Certainty Score (%)"].map(lambda x: f"{x:.1f}%")

# 全銘柄を一望できるように高さを適切に確保
st.dataframe(
    df_screener_display[["Ticker", "Company Name", "Total Value ($)", "Avg Buy Price ($)", "Key Insider", "Trade Date", "Trades", "Certainty Score (%)"]],
    use_container_width=True, hide_index=True, height=240
)

st.markdown("---")

# ==============================================================================
# 4. REALTIME ANALYSIS & CHARTS
# ==============================================================================
st.subheader(f"[{current_ticker}] Real-Time Details and Option Analysis")

# 期間選択コントロールを配置
period_col1, period_col2 = st.columns([4, 8])
with period_col1:
    selected_period = st.selectbox(
        "Historical Period:",
        options=["3mo", "6mo", "1y", "2y"],
        index=1,
        format_func=lambda x: {"3mo": "3 Months", "6mo": "6 Months (Standard)", "1y": "1 Year", "2y": "2 Years"}[x]
    )

with st.spinner(f"Analyzing market data for [{current_ticker}]..."):
    raw_hist, current_price, hv, available_expiries = fetch_market_data(current_ticker, period=selected_period)

# 新規入力されたティッカーが有効な米国株かを判定し、有効であればカスタムリストに永続追加
if raw_hist is not None and current_ticker not in all_available_tickers and current_ticker not in st.session_state.custom_tickers:
    st.session_state.custom_tickers.append(current_ticker)

if raw_hist is not None:
    hist_data = compute_technical_indicators(raw_hist)

    # 満期日の取得とガード処理
    selected_expiry = None
    if available_expiries:
        selected_expiry = st.selectbox("Select Option Expiration Date:", options=available_expiries, index=0)
    else:
        st.warning("Warning: No active option chain found for this ticker. Running in fallback simulation mode.")

    # オプションチェーンデータの取得
    with st.spinner(f"Fetching option chain..."):
        if selected_expiry:
            df_calls_raw, df_puts_raw, iv, pcr = fetch_option_chain_by_expiry(current_ticker, selected_expiry, current_price)
        else:
            df_calls_raw, df_puts_raw = pd.DataFrame(), pd.DataFrame()
            iv = hv if hv > 0 else 0.30
            pcr = 1.0

    T_30 = 30 / 365.25
    one_sigma_move = current_price * iv * np.sqrt(T_30)
    upper_1sigma = current_price + one_sigma_move
    lower_1sigma = current_price - one_sigma_move
    
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    with m_col1: st.metric("Implied Volatility (IV)", f"{iv*100:.1f}%" if selected_expiry else f"{iv*100:.1f}% (HV Fallback)")
    with m_col2: st.metric("Historical Volatility (HV)", f"{hv*100:.1f}%")
    with m_col3: st.metric("IV / HV Ratio", f"{iv/hv:.2f}" if hv > 0 else "N/A")
    with m_col4: st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}" if selected_expiry else "N/A")
    with m_col5: st.metric("1-Sigma Upper (30 Days)", f"${upper_1sigma:.2f}")
    with m_col6: st.metric("1-Sigma Lower (30 Days)", f"${lower_1sigma:.2f}")

    st.markdown("---")

    # コントロールパネル
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 3, 4])
    with ctrl_col1:
        chart_type = st.radio("Chart Type", options=["Candlestick", "Line"], horizontal=True)
    with ctrl_col2:
        overlay_indicator = st.selectbox("Overlay Indicator:", ["Bollinger Bands", "EMA (20/50)", "Ichimoku", "None"])
    with ctrl_col3:
        sub_indicator = st.selectbox("Sub Indicator:", ["RSI + MACD", "ATR (Volatility Range)"])

    # ----------------------------------------------------------------------
    # CHART 1 & 2: メイン株価チャート ＆ サブ指標（完全物理分離）
    # ----------------------------------------------------------------------
    st.markdown("### Technical Analysis Chart")

    st.html("""
        <div style='background-color: #111827; padding: 10px; border-radius: 6px; font-size: 12px; border: 1px solid #1F2937; margin-bottom: 10px; display: flex; gap: 15px; flex-wrap: wrap; align-items: center;'>
        <span style='color: #00FFCC;'>- stock price</span>
        <span style='color: #38BDF8; border-bottom: 2px dashed rgba(56, 189, 248, 0.6);'>-- 1-Sigma Range (30 Days)</span>
        <span style='color: #A855F7;'>- RSI (14)</span>
        <span style='color: #38BDF8;'>- MACD</span>
        <span style='color: #FF8C00;'>- Signal</span>
        <span style='color: #00FFCC;'>- MACD Hist (Bullish)</span>
        <span style='color: #FF007F;'>- MACD Hist (Bearish)</span>
        </div>
    """)

    # 選択された期間に応じて、表示ウィンドウ幅を調整
    slice_windows = {"3mo": 60, "6mo": 120, "1y": 250, "2y": 500}
    display_window = slice_windows.get(selected_period, 120)
    
    df_plot = hist_data.iloc[-display_window:].copy()
    plot_dates = df_plot.index
    start_date = plot_dates[0]
    end_date = plot_dates[-1]
    xaxis_range = [start_date, end_date]

    # 未来予測30日データの作成
    future_dates = [end_date + timedelta(days=i) for i in range(1, 31)]
    upper_band_curve = [current_price + (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]
    lower_band_curve = [current_price - (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]

    # 1. 独立した株価チャートを呼び出して描画
    fig_stock = draw_stock_chart(
        df_plot, chart_type, overlay_indicator, current_price, iv, 
        future_dates, upper_band_curve, lower_band_curve, xaxis_range
    )
    st.plotly_chart(fig_stock, use_container_width=True, key="stock_chart_final_v2")

    # 2. 独立したサブ指標チャートを呼び出して描画
    fig_sub = draw_sub_indicators_chart(df_plot, sub_indicator, xaxis_range)
    st.plotly_chart(fig_sub, use_container_width=True, key="sub_indicators_chart_v2")

    # ----------------------------------------------------------------------
    # CHART 3: ボラティリティ（IV/HV）歴史的推移 ＆ インサイダータイミング
    # ----------------------------------------------------------------------
    fig_vol = gr.Figure()
    hist_data["HV_20"] = hist_data["Close"].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
    hist_data["IV_Sim"] = hist_data["HV_20"] * (iv / (hv if hv > 0 else 1.0))

    fig_vol.add_trace(gr.Scatter(x=plot_dates, y=hist_data["HV_20"].iloc[-display_window:], mode="lines", line=dict(color="#FF007F", width=1.5), name="HV (%)"))
    fig_vol.add_trace(gr.Scatter(x=plot_dates, y=hist_data["IV_Sim"].iloc[-display_window:], mode="lines", line=dict(color="#00C5FF", width=1.5), name="IV (%)"))

    df_ticker_raw = df_raw[df_raw["ticker"] == current_ticker].copy()
    df_insider_daily = df_ticker_raw.groupby(["buy_date", "insider"])["total_value"].sum().reset_index()
    df_insider_daily = df_insider_daily[df_insider_daily["buy_date"].isin(hist_data.index)]

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
            offset_y = 6.0 - (date_counts[b_date] * 12.0)
            
            hover_text = f"Insider: {row['insider']}<br>Value: ${row['total_value']:,.0f}"
            show_in_legend = insider not in registered_legends
            if show_in_legend:
                registered_legends.add(insider)
            
            fig_vol.add_trace(gr.Scatter(
                x=[b_date], y=[offset_y], mode="markers",
                marker=dict(symbol="star", size=14, color=color, line=dict(color="#FFFFFF", width=1.2)),
                text=[hover_text], hoverinfo="text", legendgroup=insider, name=f"Insider: {insider}", showlegend=show_in_legend
            ))
            
    fig_vol.update_layout(
        height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=130, t=50, b=10), 
        legend=dict(orientation="v", y=1, x=1.02, xanchor="left", yanchor="top"),
        xaxis=dict(title="Date", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis=dict(title="Volatility (%)", range=[-25, 105], showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        hovermode="x unified", hoverlabel=dict(bgcolor="rgba(17, 24, 39, 0.85)", font_size=11, font_family="Consolas, monospace")
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")

    # ==============================================================================
    # 🎯 強化された動的オプション推奨戦略アルゴリズム
    # ==============================================================================
    st.subheader("Statistical Option Strategy Ranking")

    # デフォルト値の設定（オプションチェーンが空だった場合のフォールバック）
    bc_buy_strike, bc_sell_strike, bc_buy_prem, bc_sell_prem = round(current_price * 0.95, 1), round(upper_1sigma, 1), round(current_price * 0.08, 2), round(current_price * 0.02, 2)
    cc_buy_stock, cc_sell_strike, cc_sell_prem = current_price, round(upper_1sigma, 1), round(current_price * 0.05, 2)
    lc_strike, lc_prem = round(current_price * 1.05, 1), round(current_price * 0.04, 2)
    
    bc_valid, cc_valid, lc_valid = False, False, False

    # リアルタイムオプションチェーンが存在する場合、動的ストライク探索を実行
    if not df_calls_raw.empty:
        try:
            # 1. ブル・コール・スプレッド用の実契約探索
            calls_itm = df_calls_raw[df_calls_raw["Delta"].between(0.60, 0.75)]
            if calls_itm.empty:
                calls_itm = df_calls_raw[df_calls_raw["strike"] < current_price]
            
            calls_otm = df_calls_raw[df_calls_raw["Delta"].between(0.25, 0.40)]
            if calls_otm.empty:
                calls_otm = df_calls_raw[df_calls_raw["strike"] >= upper_1sigma]

            if not calls_itm.empty and not calls_otm.empty:
                best_itm = calls_itm.sort_values(by="openInterest", ascending=False).iloc[0]
                potential_otms = calls_otm[calls_otm["strike"] > best_itm["strike"]]
                if not potential_otms.empty:
                    best_otm = potential_otms.sort_values(by="openInterest", ascending=False).iloc[0]
                    
                    bc_buy_strike = best_itm["strike"]
                    bc_sell_strike = best_otm["strike"]
                    bc_buy_prem = best_itm["lastPrice"] if best_itm["lastPrice"] > 0 else (current_price - bc_buy_strike)
                    bc_sell_prem = best_otm["lastPrice"] if best_otm["lastPrice"] > 0 else (current_price * 0.02)
                    bc_valid = True

            # 2. カバード・コール用の実契約探索
            cc_calls = df_calls_raw[df_calls_raw["Delta"].between(0.15, 0.25)]
            if cc_calls.empty:
                cc_calls = df_calls_raw[df_calls_raw["strike"] > current_price]
            
            if not cc_calls.empty:
                best_cc_call = cc_calls.sort_values(by="openInterest", ascending=False).iloc[0]
                cc_buy_stock = current_price
                cc_sell_strike = best_cc_call["strike"]
                cc_sell_prem = best_cc_call["lastPrice"] if best_cc_call["lastPrice"] > 0 else (current_price * 0.03)
                cc_valid = True

            # 3. ロング・コール用の実契約探索
            lc_calls = df_calls_raw[df_calls_raw["Delta"].between(0.45, 0.55)]
            if lc_calls.empty:
                lc_calls = df_calls_raw.copy()
            
            if not lc_calls.empty:
                lc_calls["diff"] = (lc_calls["strike"] - current_price).abs()
                best_lc_call = lc_calls.sort_values(by="diff").iloc[0]
                lc_strike = best_lc_call["strike"]
                lc_prem = best_lc_call["lastPrice"] if best_lc_call["lastPrice"] > 0 else (current_price * 0.05)
                lc_valid = True
        except Exception as opt_err:
            st.sidebar.warning(f"Option strategy error: {opt_err}")

    # --- 統計数値の動的計算 ---
    # 1. ブル・コール・スプレッド
    bc_net_cost = max(0.10, bc_buy_prem - bc_sell_prem)
    bc_max_profit = max(0.10, (bc_sell_strike - bc_buy_strike) - bc_net_cost)
    bc_roi = (bc_max_profit / bc_net_cost) * 100
    bc_prob = 65.0 + (10.0 if iv > hv else -5.0)

    # 2. カバード・コール
    cc_net_cost = max(1.0, cc_buy_stock - cc_sell_prem)
    cc_max_profit = (cc_sell_strike - cc_buy_stock) + cc_sell_prem
    cc_roi = (cc_max_profit / cc_net_cost) * 100
    cc_prob = 80.0 + (5.0 if iv > hv else 0.0)

    # 3. ロング・コール
    lc_roi = 150.0 + (50.0 if iv < hv else -30.0)
    lc_prob = 45.0 + (10.0 if iv < hv else -10.0)

    # オプションチェーン未存在時の文言調整
    source_label = "[Dynamic Chain Selection]" if selected_expiry else "[Theoretical Simulation]"

    strategies_pool = [
        {
            "id": "bull_call", 
            "title": "Bull Call Spread", 
            "class": "strategy-card", 
            "roi": bc_roi, 
            "prob": bc_prob,
            "desc": f"<b>[Statistical Basis]</b><br>"
                    f"IV/HV ratio is <b>{(iv/hv if hv > 0 else 1.0):.2f}</b>.<br>"
                    f"Combining ITM Call buying and OTM Call selling offsets theta decay while securing a high probability of success.<br><br>"
                    f"<b>{source_label}</b><br>"
                    f"1. <b>Buy {current_ticker} ${bc_buy_strike:.1f} Call (ITM)</b> (Est: ${bc_buy_prem:.2f})<br>"
                    f"2. <b>Sell {current_ticker} ${bc_sell_strike:.1f} Call (OTM)</b> (Est: ${bc_sell_prem:.2f})<br><br>"
                    f"<b>[Risk/Return Profile]</b><br>"
                    f"* <b>Max Loss (Net Cost)</b>: <b>${bc_net_cost:.2f}</b> (${bc_net_cost*100:.0f})<br>"
                    f"* <b>Max Profit</b>: <b>${bc_max_profit:.2f}</b> (${bc_max_profit*100:.0f})<br>"
                    f"* <b>Expected ROI</b>: <span style='color: #00FFCC; font-weight: bold;'>+{bc_roi:.1f}%</span><br>"
                    f"* <b>Probability of Profit</b>: <b>{bc_prob:.1f}%</b>"
        },
        {
            "id": "covered_call", 
            "title": "Covered Call", 
            "class": "strategy-card-secondary", 
            "roi": cc_roi, 
            "prob": cc_prob,
            "desc": f"<b>[Statistical Basis]</b><br>"
                    f"IV/HV ratio is <b>{(iv/hv if hv > 0 else 1.0):.2f}</b>.<br>"
                    f"Own the stock and sell OTM call options to collect premium (income gain).<br><br>"
                    f"<b>{source_label}</b><br>"
                    f"1. <b>Buy Stock at ${current_price:.2f}</b><br>"
                    f"2. <b>Sell {current_ticker} ${cc_sell_strike:.1f} Call (OTM)</b> (Est Premium: ${cc_sell_prem:.2f})<br><br>"
                    f"<b>[Risk/Return Profile]</b><br>"
                    f"* <b>Net Cost</b>: <b>${cc_net_cost:.2f}</b><br>"
                    f"* <b>Max Profit</b>: <b>${cc_max_profit:.2f}</b> (Expected ROI: <span style='color: #38BDF8; font-weight: bold;'>+{cc_roi:.1f}%</span>)<br>"
                    f"* <b>Probability of Profit</b>: <b>{cc_prob:.1f}%</b>"
        },
        {
            "id": "long_call", 
            "title": "Long Call", 
            "class": "strategy-card-warning", 
            "roi": lc_roi, 
            "prob": lc_prob,
            "desc": f"<b>[Statistical Basis]</b><br>"
                    f"High-leverage strategy targeting sharp upward moves following heavy insider cluster buying.<br><br>"
                    f"<b>{source_label}</b><br>"
                    f"* <b>Buy {current_ticker} ${lc_strike:.1f} Call (ATM/OTM)</b> (Est: ${lc_prem:.2f})<br><br>"
                    f"<b>[Risk/Return Profile]</b><br>"
                    f"* <b>Max Loss</b>: Premium Paid <b>${lc_prem:.2f}</b> (Limited Risk)<br>"
                    f"* <b>Max Profit</b>: Unlimited<br>"
                    f"* <b>Probability of Profit</b>: <b>{lc_prob:.1f}%</b>"
        }
    ]

    # ROI（リターン効率）の高い順にランキング表示
    ranked_strategies = sorted(strategies_pool, key=lambda x: x["roi"], reverse=True)
    rank_medals = ["🥇 1st Active Strategy", "🥈 2nd Alternative Strategy", "🥉 3rd Tactical Strategy"]
    for idx, strat in enumerate(ranked_strategies[:3]):
        st.html(f"""
            <div class="{strat['class']}">
                <div style="font-size: 11px; font-weight: bold; color: #94A3B8; margin-bottom: 4px;">{rank_medals[idx]}</div>
                <h3 style="color: #00FFCC; margin-top: 0; margin-bottom: 12px;">{strat['title']}</h3>
                <div style="font-size: 13px; line-height: 1.7; color: #E2E8F0;">{strat['desc']}</div>
            </div>
        """)

    # ペイオフ・ダイアグラム
    best_strat = ranked_strategies[0]["id"]
    st.markdown("#### Payoff Diagram: Return vs Underlying Change (%)")
    stock_changes = np.linspace(-0.20, 0.20, 100)
    underlying_prices = current_price * (1 + stock_changes)
    payoffs = []
    
    if best_strat == "bull_call":
        for S in underlying_prices:
            p_buy = max(0, S - bc_buy_strike) - bc_buy_prem
            p_sell = bc_sell_prem - max(0, S - bc_sell_strike)
            payoffs.append((p_buy + p_sell) / bc_net_cost * 100)
        breakeven_price = bc_buy_strike + bc_net_cost
    elif best_strat == "covered_call":
        for S in underlying_prices:
            stock_profit = S - current_price
            call_profit = cc_sell_prem - max(0, S - cc_sell_strike)
            payoffs.append((stock_profit + call_profit) / cc_net_cost * 100)
        breakeven_price = cc_buy_stock - cc_sell_prem
    else:
        for S in underlying_prices:
            payoffs.append((max(0, S - lc_strike) - lc_prem) / lc_prem * 100)
        breakeven_price = lc_strike + lc_prem
            
    breakeven_change = ((breakeven_price / current_price) - 1) * 100
    
    fig_payoff = gr.Figure()
    fig_payoff.add_vrect(x0=-iv*np.sqrt(T_30)*100, x1=iv*np.sqrt(T_30)*100, fillcolor="rgba(0, 255, 204, 0.05)", line_width=0, annotation_text="1-Sigma Range", annotation_position="top left", annotation_font=dict(size=10, color="rgba(0, 255, 204, 0.5)"))
    fig_payoff.add_trace(gr.Scatter(x=stock_changes * 100, y=payoffs, mode="lines", line=dict(color="#00FFCC", width=3)))
    fig_payoff.add_vline(x=breakeven_change, line_dash="dash", line_color="#FF007F")
    fig_payoff.add_hline(y=0, line_color="rgba(255, 255, 255, 0.2)", line_width=1)
    fig_payoff.update_layout(height=240, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19", margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="Underlying Change (%)"), yaxis=dict(title="Return (%)"), showlegend=False)
    st.plotly_chart(fig_payoff, use_container_width=True)
    st.caption(f"Break-even: {breakeven_change:+.1f}% (${breakeven_price:.2f})")

else:
    st.error(f"Error: Invalid Ticker '{current_ticker}'. Please check and try again.")
    if current_ticker in st.session_state.custom_tickers:
        st.session_state.custom_tickers.remove(current_ticker)
    st.stop()

# ==============================================================================
# 5. T-SHAPE OPTION CHAIN MATRIX
# ==============================================================================
st.markdown("---")
st.markdown(f"### Options Chain: [{current_ticker}] T-Shape Matrix")

if selected_expiry:
    st.html("""
        <div class="guide-panel">
            <h4 style="color: #38BDF8; margin-top: 0; margin-bottom: 12px;">Option Metrics Guide</h4>
            <div style="font-size: 12px; line-height: 1.6; color: #94A3B8;">
                <table style="width: 100%; border-collapse: collapse; color: #E2E8F0;">
                    <thead>
                        <tr style="border-bottom: 1px solid #1E293B; text-align: left;">
                            <th style="padding: 6px;">Metric</th>
                            <th style="padding: 6px;">Meaning</th>
                            <th style="padding: 6px;">High Value</th>
                            <th style="padding: 6px;">Low Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">Delta</td>
                            <td style="padding: 6px;">Sensitivity / Probability of expiring ITM</td>
                            <td style="padding: 6px; color: #38BDF8;">ITM (High Win Rate)</td>
                            <td style="padding: 6px;">OTM (High Leverage)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">IV</td>
                            <td style="padding: 6px;">Implied Volatility / Premium pricing level</td>
                            <td style="padding: 6px; color: #FF007F;">Overvalued (Favors Sellers)</td>
                            <td style="padding: 6px; color: #38BDF8;">Undervalued (Favors Buyers)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">OI</td>
                            <td style="padding: 6px;">Open Interest / Active contracts</td>
                            <td style="padding: 6px; color: #38BDF8;">Strong Support/Resistance</td>
                            <td style="padding: 6px;">Thin Liquidity</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    """)

    if hist_data is not None and not df_calls_raw.empty:
        df_c = df_calls_raw[["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"]].copy()
        df_p = df_puts_raw[["strike", "lastPrice", "volume", "openInterest", "impliedVolatility", "Delta"]].copy()
        
        df_t_shape = pd.merge(df_c, df_p, on="strike", suffixes=("_call", "_put"))
        df_t_shape = df_t_shape.sort_values(by="strike").reset_index(drop=True)
        
        df_t_shape_display = pd.DataFrame()
        df_t_shape_display["Call Delta"] = df_t_shape["Delta_call"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
        df_t_shape_display["Call IV"] = df_t_shape["impliedVolatility_call"].map(lambda x: f"{x*100:.1f}%")
        df_t_shape_display["Call OI"] = df_t_shape["openInterest_call"].fillna(0).astype(int)
        df_t_shape_display["Call Vol"] = df_t_shape["volume_call"].fillna(0).astype(int)
        df_t_shape_display["Call Price"] = df_t_shape["lastPrice_call"].map(lambda x: f"${x:.2f}")
        
        df_t_shape_display["Strike"] = df_t_shape["strike"].map(lambda x: f"${x:.1f}")
        
        df_t_shape_display["Put Price"] = df_t_shape["lastPrice_put"].map(lambda x: f"${x:.2f}")
        df_t_shape_display["Put Vol"] = df_t_shape["volume_put"].fillna(0).astype(int)
        df_t_shape_display["Put OI"] = df_t_shape["openInterest_put"].fillna(0).astype(int)
        df_t_shape_display["Put IV"] = df_t_shape["impliedVolatility_put"].map(lambda x: f"{x*100:.1f}%")
        df_t_shape_display["Put Delta"] = df_t_shape["Delta_put"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
        
        st.dataframe(
            df_t_shape_display[[
                "Call Delta", "Call IV", "Call OI", "Call Vol", "Call Price", 
                "Strike", 
                "Put Price", "Put Vol", "Put OI", "Put IV", "Put Delta"
            ]],
            use_container_width=True, hide_index=True, height=320
        )
    else:
        st.warning("Warning: Options data not available.")
else:
    st.info("Info: No option chain available for this ticker.")

# ==============================================================================
# 6. NEWS TERMINAL
# ==============================================================================
st.markdown("---")
st.markdown(f"### Events and Corporate Catalyst Terminal: [{current_ticker}]")

if hist_data is not None:
    raw_events_by_date = {}
    df_catalysts = fetch_catalyst_events(current_ticker, df_raw)
    df_ticker_raw = df_raw[df_raw["ticker"] == current_ticker].copy()
    df_insider_grouped = df_ticker_raw.groupby(["buy_date", "insider"]).agg({
        "total_value": "sum", "position": "first", "filing_url": "first"
    }).reset_index()

    for _, trade in df_insider_grouped.iterrows():
        t_date = trade["buy_date"]
        if t_date not in raw_events_by_date: raw_events_by_date[t_date] = []
        raw_events_by_date[t_date].append({
            "type": "I", "insider": trade["insider"], "position": trade["position"],
            "value": trade["total_value"], "url": trade["filing_url"]
        })

    if not df_catalysts.empty:
        for _, row in df_catalysts.iterrows():
            c_date = pd.to_datetime(row["date"])
            if c_date not in raw_events_by_date: raw_events_by_date[c_date] = []
            raw_events_by_date[c_date].append({
                "type": "C", "category": row["category"], "title": row["title"], "url": row["source_url"]
            })

if hist_data is not None and 'raw_events_by_date' in locals() and raw_events_by_date:
    linked_sources_list = []
    for event_date in sorted(raw_events_by_date.keys(), reverse=True):
        date_str = event_date.strftime('%Y-%m-%d')
        prev_day = (event_date - timedelta(days=1)).strftime('%Y-%m-%d')
        next_day = (event_date + timedelta(days=1)).strftime('%Y-%m-%d')
        date_specific_news_url = f"https://www.google.com/search?q={current_ticker}+stock+news+after:{prev_day}+before:{next_day}&tbm=nws"
        
        for item in raw_events_by_date[event_date]:
            if item["type"] == "I":
                linked_sources_list.append([
                    date_str, "Insider [ I ]",
                    f"{item['insider']} ({item['position']}) bought ${item['value']:,.0f}",
                    item["url"], date_specific_news_url,
                    f"https://finviz.com/quote.ashx?t={current_ticker}"
                ])
            else:
                linked_sources_list.append([
                    date_str, "Catalyst [ R ]",
                    f"[{item['category']}] {item['title']}",
                    f"https://www.sec.gov/edgar/browse/?CIK={current_ticker}",
                    item["url"],
                    f"https://finviz.com/quote.ashx?t={current_ticker}"
                ])
                
    if linked_sources_list:
        df_sources = pd.DataFrame(linked_sources_list, columns=["Date", "Type", "Event Summary", "SEC Link", "Google News", "Finviz Chart"])
        st.dataframe(
            df_sources,
            column_config={
                "SEC Link": st.column_config.LinkColumn("SEC Link", display_text="Form 4"),
                "Google News": st.column_config.LinkColumn("Google News", display_text="News"),
                "Finviz Chart": st.column_config.LinkColumn("Finviz Chart", display_text="Chart")
            },
            use_container_width=True, hide_index=True, height=250
        )
else:
    st.info("No linked event history found.")
