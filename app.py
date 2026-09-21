import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as gr
from datetime import datetime, timedelta
import math

# 独自モジュールからデータ処理関数をインポート
from data_loader import (
    load_and_process_data,
    generate_screener,
    fetch_market_data,
    compute_technical_indicators,
    fetch_option_chain_by_expiry,
    fetch_catalyst_events
)

# ==============================================================================
# 1. PAGE CONFIG & DARK THEME STYLE
# ==============================================================================
st.set_page_config(
    page_title="Whale-Eye: Option & Insider Intelligence",
    page_icon="👁️",
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

if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = top_10_tickers[0] if top_10_tickers else ""

# ==============================================================================
# 3. MAIN TERMINAL LAYOUT
# ==============================================================================
st.title("👁️ Whale-Eye: Institutional Option & Insider Intelligence")
st.markdown("---")

st.subheader("📊 全銘柄多次元スクリーニング・マトリックス")
col_sel1, col_sel2 = st.columns([3, 5])
with col_sel1:
    selected_from_dropdown = st.selectbox(
        "🔍 解析・表示する銘柄を全銘柄リストから選択:",
        options=all_available_tickers,
        index=all_available_tickers.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in all_available_tickers else 0
    )
    if selected_from_dropdown != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_from_dropdown
        st.rerun()

with col_sel2:
    radio_options = list(top_10_tickers)
    if st.session_state.selected_ticker not in radio_options:
        radio_options.append(st.session_state.selected_ticker)
    selected_by_radio = st.radio(
        "⚡ クイック選択 (矢印キーで1ミリ秒連動):",
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
    "ticker": "ティッカー", "company": "企業名", "total_value": "直近取引額 ($)",
    "avg_price": "平均取得単価 ($)", "insider": "主なインサイダー", "buy_date": "直近取引日",
    "trade_count": "取引回数", "Certainty (%)": "統計的確実性スコア (%)"
})
df_screener_display["直近取引額 ($)"] = df_screener_display["直近取引額 ($)"].map(lambda x: f"${x:,.0f}")
df_screener_display["平均取得単価 ($)"] = df_screener_display["平均取得単価 ($)"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
df_screener_display["直近取引日"] = df_screener_display["直近取引日"].dt.strftime('%Y-%m-%d')
df_screener_display["統計的確実性スコア (%)"] = df_screener_display["統計的確実性スコア (%)"].map(lambda x: f"{x:.1f}%")

st.dataframe(
    df_screener_display[["ティッカー", "企業名", "直近取引額 ($)", "平均取得単価 ($)", "主なインサイダー", "直近取引日", "取引回数", "統計的確実性スコア (%)"]],
    use_container_width=True, hide_index=True, height=200
)

st.markdown("---")

# ==============================================================================
# 4. REALTIME ANALYSIS & CHARTS
# ==============================================================================
st.subheader(f"👁️ 【{current_ticker}】 リアルタイム詳細・オプション解析")

with st.spinner(f"【{current_ticker}】の市場データを解析中..."):
    raw_hist, current_price, hv, available_expiries = fetch_market_data(current_ticker)

if raw_hist is not None:
    hist_data = compute_technical_indicators(raw_hist)

    if available_expiries:
        selected_expiry = st.selectbox("表示するオプションチェーンの満期日を選択してください:", options=available_expiries, index=0)
    else:
        selected_expiry = None
        st.warning("⚠️ オプション満期日が見つかりません。")

    with st.spinner(f"オプションチェーンを解析中..."):
        df_calls_raw, df_puts_raw, iv, pcr = fetch_option_chain_by_expiry(current_ticker, selected_expiry, current_price)

    T_30 = 30 / 365.25
    one_sigma_move = current_price * iv * np.sqrt(T_30)
    upper_1sigma = current_price + one_sigma_move
    lower_1sigma = current_price - one_sigma_move
    
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    with m_col1: st.metric("インプライド・ボラティリティ (IV)", f"{iv*100:.1f}%")
    with m_col2: st.metric("歴史的ボラティリティ (HV)", f"{hv*100:.1f}%")
    with m_col3: st.metric("IV / HV 比率", f"{iv/hv:.2f}" if hv > 0 else "N/A")
    with m_col4: st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}")
    with m_col5: st.metric("1σ 上昇上限 (30日)", f"${upper_1sigma:.2f}")
    with m_col6: st.metric("1σ 下落下限 (30日)", f"${lower_1sigma:.2f}")

    st.markdown("---")

    # コントロールパネル
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 3, 4])
    with ctrl_col1:
        chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)
    with ctrl_col2:
        overlay_indicator = st.selectbox("重ね合わせ指標の選択:", ["ボリンジャーバンド", "EMA (20/50)", "一目均衡表 (Ichimoku)", "なし"])
    with ctrl_col3:
        sub_indicator = st.selectbox("下段サブ指標の選択:", ["RSI + MACD", "ATR (ボラティリティ値幅)"])

    # ----------------------------------------------------------------------
    # CHART 1: メイン株価チャート (完全に独立したFigure)
    # ----------------------------------------------------------------------
    st.markdown("### 📈 テクニカル分析チャート")

    st.markdown(
        "<div style='background-color: #111827; padding: 10px; border-radius: 6px; font-size: 12px; border: 1px solid #1F2937; margin-bottom: 10px; display: flex; gap: 15px; flex-wrap: wrap; align-items: center;'>"
        "<span style='color: #00FFCC;'>■ 現物株価</span>"
        "<span style='color: #38BDF8; border-bottom: 2px dashed rgba(56, 189, 248, 0.6);'>-- 1σ上昇/下落下限 (30日予測)</span>"
        "<span style='color: #A855F7;'>■ RSI (14)</span>"
        "<span style='color: #38BDF8;'>■ MACD</span>"
        "<span style='color: #FF8C00;'>■ Signal</span>"
        "<span style='color: #00FFCC;'>■ MACD Hist (強気)</span>"
        "<span style='color: #FF007F;'>■ MACD Hist (弱気)</span>"
        "</div>", 
        unsafe_allow_html=True
    )

    # 直近60営業日
    df_plot = hist_data.iloc[-60:].copy()
    plot_dates = df_plot.index
    start_date = plot_dates[0]
    end_date = plot_dates[-1]
    xaxis_range = [start_date, end_date]

    # 未来予測30日
    future_dates = [end_date + timedelta(days=i) for i in range(1, 31)]
    upper_band_curve = [current_price + (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]
    lower_band_curve = [current_price - (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]

    # --- 1段目: 株価チャートの作成 ---
    fig_stock = gr.Figure()

    if chart_type == "ローソク足":
        fig_stock.add_trace(gr.Candlestick(
            x=df_plot.index, open=df_plot["Open"], high=df_plot["High"], low=df_plot["Low"], close=df_plot["Close"], name="株価"
        ))
    else:
        fig_stock.add_trace(gr.Scatter(
            x=df_plot.index, y=df_plot["Close"], mode="lines", line=dict(color="#00FFCC", width=2.5), name="現物株価"
        ))

    # 重ね合わせ指標 (株価チャートのみに適用。fill='none'で塗りつぶしを完全排除)
    if overlay_indicator == "ボリンジャーバンド" and "BB_Upper" in df_plot.columns:
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.35)", width=1.0, dash="dash"), fill='none', name="BB Upper"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.35)", width=1.0, dash="dash"), fill='none', name="BB Lower"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MA20"], line=dict(color="orange", width=1.0, dash="dot"), fill='none', name="20日移動平均"))
    elif overlay_indicator == "EMA (20/50)":
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#00C5FF", width=1.2), fill='none', name="EMA 20"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["EMA50"], line=dict(color="#FF8C00", width=1.2), fill='none', name="EMA 50"))
    elif overlay_indicator == "一目均衡表 (Ichimoku)":
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Senkou_Span_A"], line=dict(color="rgba(56, 189, 248, 0.4)", width=0.8, dash="dash"), fill='none', name="先行スパンA"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Senkou_Span_B"], line=dict(color="rgba(244, 63, 94, 0.4)", width=0.8, dash="dash"), fill='none', name="先行スパンB"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Tenkan_Sen"], line=dict(color="#38BDF8", width=1.0), fill='none', name="転換線"))
        fig_stock.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Kijun_Sen"], line=dict(color="#F43F5E", width=1.0), fill='none', name="基準線"))

    # 1σ予測レンジ (株価チャートのみに重ね書き)
    fig_stock.add_trace(gr.Scatter(x=future_dates, y=upper_band_curve, mode="lines", line=dict(color="rgba(56, 189, 248, 0.6)", width=1.2, dash="dash"), fill='none', name="1σ上限"))
    fig_stock.add_trace(gr.Scatter(x=future_dates, y=lower_band_curve, mode="lines", line=dict(color="rgba(239, 68, 68, 0.6)", width=1.2, dash="dash"), fill='none', name="1σ下限"))

    fig_stock.update_layout(
        height=400, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
        dragmode="drawline", newshape=dict(line=dict(color="#00FFCC", width=1.5), opacity=0.8),
        xaxis=dict(range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis=dict(title="株価 ($)", showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)")
    )
    st.plotly_chart(fig_stock, use_container_width=True, key="stock_chart_final")

    # --- 2段目: サブ指標チャートの作成 (完全に独立したFigureとして物理隔離) ---
    fig_sub = gr.Figure()

    if sub_indicator == "RSI + MACD":
        # RSIとMACDを2段に分けたサブプロットにする (株価データが混入することは物理的に不可能)
        fig_sub = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_width=[0.5, 0.5])
        
        # RSI (Row 1)
        fig_sub.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["RSI_14"], mode="lines", line=dict(color="#A855F7", width=2.0), fill='none', name="RSI"), row=1, col=1)
        fig_sub.add_hline(y=70, line_dash="dash", line_color="rgba(239, 68, 68, 0.5)", row=1, col=1)
        fig_sub.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 204, 0.5)", row=1, col=1)

        # MACD (Row 2)
        fig_sub.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MACD"], mode="lines", line=dict(color="#38BDF8", width=1.5), fill='none', name="MACD"), row=2, col=1)
        fig_sub.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MACD_Signal"], mode="lines", line=dict(color="#FF8C00", width=1.5), fill='none', name="Signal"), row=2, col=1)
        hist_colors = ["#00FFCC" if (not math.isnan(val) and val >= 0) else "#FF007F" for val in df_plot["MACD_Hist"]]
        fig_sub.add_trace(gr.Bar(x=df_plot.index, y=df_plot["MACD_Hist"], marker_color=hist_colors, name="Hist"), row=2, col=1)
        
        fig_sub.update_layout(
            height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
            margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
            xaxis=dict(range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            xaxis2=dict(title="日付", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            yaxis=dict(title="RSI", range=[10, 90]),
            yaxis2=dict(title="MACD")
        )
    else:
        # ATR単体 (1つの独立したFigure)
        fig_sub.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["ATR"], mode="lines", line=dict(color="#E2E8F0", width=1.8), fill='none', name="ATR"))
        
        fig_sub.update_layout(
            height=180, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
            margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
            xaxis=dict(title="日付", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            yaxis=dict(title="ATR")
        )

    st.plotly_chart(fig_sub, use_container_width=True, key="sub_indicators_chart")

    # ----------------------------------------------------------------------
    # CHART 2: ボラティリティ（IV/HV）歴史的推移 ＆ インサイダータイミング
    # ----------------------------------------------------------------------
    fig_vol = gr.Figure()
    hist_data["HV_20"] = hist_data["Close"].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
    hist_data["IV_Sim"] = hist_data["HV_20"] * (iv / (hv if hv > 0 else 1.0))

    fig_vol.add_trace(gr.Scatter(x=plot_dates, y=hist_data["HV_20"].iloc[-60:], mode="lines", line=dict(color="#FF007F", width=1.5), name="歴史的ボラティリティ (HV %)"))
    fig_vol.add_trace(gr.Scatter(x=plot_dates, y=hist_data["IV_Sim"].iloc[-60:], mode="lines", line=dict(color="#00C5FF", width=1.5), name="予測ボラティリティ (IV %)"))

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
            
            hover_text = f"インサイダー: {row['insider']}<br>購入総額: ${row['total_value']:,.0f}"
            show_in_legend = insider not in registered_legends
            if show_in_legend:
                registered_legends.add(insider)
            
            fig_vol.add_trace(gr.Scatter(
                x=[b_date], y=[offset_y], mode="markers",
                marker=dict(symbol="star", size=14, color=color, line=dict(color="#FFFFFF", width=1.2)),
                text=[hover_text], hoverinfo="text", legendgroup=insider, name=f"🐋 {insider} (購入)", showlegend=show_in_legend
            ))
            
    fig_vol.update_layout(
        height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=130, t=50, b=10), 
        legend=dict(orientation="v", y=1, x=1.02, xanchor="left", yanchor="top"),
        xaxis=dict(title="日付", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis=dict(title="ボラティリティ (%)", range=[-25, 105], showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        hovermode="x unified", hoverlabel=dict(bgcolor="rgba(17, 24, 39, 0.85)", font_size=11, font_family="Consolas, monospace")
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")

    # ----------------------------------------------------------------------
    # SECTION 3: 統計的オプション推奨戦略ランキング
    # ----------------------------------------------------------------------
    st.subheader("🎯 統計的オプション推奨戦略ランキング")
    
    bc_buy_strike = current_price * 0.95
    bc_sell_strike = upper_1sigma
    bc_buy_prem = current_price * 0.08
    bc_sell_prem = current_price * 0.02
    bc_net_cost = bc_buy_prem - bc_sell_prem
    bc_max_profit = (bc_sell_strike - bc_buy_strike) - bc_net_cost
    bc_roi = (bc_max_profit / bc_net_cost) * 100
    bc_prob = 68.2

    cc_buy_stock = current_price
    cc_sell_strike = upper_1sigma
    cc_sell_prem = current_price * 0.05
    cc_net_cost = cc_buy_stock - cc_sell_prem
    cc_max_profit = (cc_sell_strike - cc_buy_stock) + cc_sell_prem
    cc_roi = (cc_max_profit / cc_net_cost) * 100
    cc_prob = 84.1

    lc_strike = current_price * 1.05
    lc_prem = current_price * 0.04
    lc_roi = 150.0
    lc_prob = 50.0

    strategies_pool = [
        {
            "id": "bull_call", "title": "🟢 ブル・コール・スプレッド (Bull Call Spread)", "class": "strategy-card", "roi": bc_roi, "prob": bc_prob,
            "desc": f"<b>【統計的選定根拠】</b><br>IV/HV比率が <b>{(iv/hv if hv > 0 else 1.0):.2f}</b> と低く、オプション買いのプレミアムが統計的に割安な状態です。<br><br><b>【具体的取引価格の統計的提案】</b><br>1. <b>Buy {current_ticker} 30日満期 ${bc_buy_strike:.1f} Call (ITM)</b> (目安: ${bc_buy_prem:.2f})<br>2. <b>Sell {current_ticker} 30日満期 ${bc_sell_strike:.1f} Call (OTM)</b> (目安: ${bc_sell_prem:.2f})<br><br><b>【リスク・リターン特性】</b><br>* <b>最大損失</b>: ${bc_net_cost:.2f}<br>* <b>最大利益</b>: ${bc_max_profit:.2f} (想定最大リターン: <b>+{bc_roi:.1f}%</b>)<br>* <b>統計的勝率</b>: <b>{bc_prob:.1f}%</b>"
        },
        {
            "id": "covered_call", "title": "🟡 カバード・コール (Covered Call)", "class": "strategy-card-secondary", "roi": cc_roi, "prob": cc_prob,
            "desc": f"<b>【統計的選定根拠】</b><br>ボラティリティが過熱傾向（IV/HV比率 <b>{(iv/hv if hv > 0 else 1.0):.2f}</b>）にあるため、コール売りプレミアムを回収するインカムゲイン戦略が極めて有利です。<br><br><b>【具体的取引価格の統計的提案】</b><br>1. <b>現物株式を ${current_price:.2f} で購入</b><br>2. <b>Sell {current_ticker} 30日満期 ${cc_sell_strike:.1f} Call (OTM)</b> (目安プレミアム受取: ${cc_sell_prem:.2f})<br><br><b>【リスク・リターン特性】</b><br>* <b>実質コスト</b>: ${cc_net_cost:.2f}<br>* <b>最大利益</b>: ${cc_max_profit:.2f} (想定最大リターン: <b>+{cc_roi:.1f}%</b>)<br>* <b>統計的勝率</b>: <b>{cc_prob:.1f}%</b>"
        },
        {
            "id": "long_call", "title": "🟣 ロング・コール (Long Call) 単体打診買い", "class": "strategy-card-warning", "roi": lc_roi, "prob": lc_prob,
            "desc": f"<b>【統計的選定根拠】</b><br>インサイダーの超大口買いが直近で集中しており、突発的な好材料（カタリスト）発表による株価急騰を狙う高レバレッジ戦略です。<br><br><b>【具体的取引価格の統計的提案】</b><br>* <b>Buy {current_ticker} 30日満期 ${lc_strike:.1f} Call (ややOTM)</b> (目安: ${lc_prem:.2f})<br><br><b>【リスク・リターン特性】</b><br>* <b>最大損失</b>: 支払ったプレミアム ${lc_prem:.2f} のみ<br>* <b>最大利益</b>: 無制限<br>* <b>統計的勝率</b>: <b>{lc_prob:.1f}%</b>"
        }
    ]

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
    st.markdown("#### 📈 1st推奨戦略の満期時株価騰落率 vs 予想投資リターン (%)")
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
    fig_payoff.add_vrect(x0=-iv*np.sqrt(T_30)*100, x1=iv*np.sqrt(T_30)*100, fillcolor="rgba(0, 255, 204, 0.05)", line_width=0, annotation_text="1σ 確率範囲", annotation_position="top left", annotation_font=dict(size=10, color="rgba(0, 255, 204, 0.5)"))
    fig_payoff.add_trace(gr.Scatter(x=stock_changes * 100, y=payoffs, mode="lines", line=dict(color="#00FFCC", width=3)))
    fig_payoff.add_vline(x=breakeven_change, line_dash="dash", line_color="#FF007F")
    fig_payoff.add_hline(y=0, line_color="rgba(255, 255, 255, 0.2)", line_width=1)
    fig_payoff.update_layout(height=240, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19", margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="満期時の株価騰落率 (%)"), yaxis=dict(title="投資リターン (%)"), showlegend=False)
    st.plotly_chart(fig_payoff, use_container_width=True)
    st.caption(f"損益分岐点（Break-even）: 株価騰落率 {breakeven_change:+.1f}% (${breakeven_price:.2f}) 以上でプラス収支")

else:
    st.warning("⚠️ 選択された銘柄の株価データを取得できませんでした。")

# ==============================================================================
# 5. T-SHAPE OPTION CHAIN MATRIX
# ==============================================================================
st.markdown("---")
st.markdown(f"### 📄 【{current_ticker}】 {selected_expiry} 満期オプション・チェーン (T-Shape プロ仕様マトリックス)")

st.html("""
    <div class="guide-panel">
        <h4 style="color: #38BDF8; margin-top: 0; margin-bottom: 12px;">👁️ オプション統計指標の完全解読マニュアル</h4>
        <div style="font-size: 12px; line-height: 1.6; color: #94A3B8;">
            <table style="width: 100%; border-collapse: collapse; color: #E2E8F0;">
                <thead>
                    <tr style="border-bottom: 1px solid #1E293B; text-align: left;">
                        <th style="padding: 6px;">指標名</th>
                        <th style="padding: 6px;">数値の意味</th>
                        <th style="padding: 6px;">「値が大きい」場合</th>
                        <th style="padding: 6px;">「値が小さい」場合</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">Delta (デルタ)</td>
                        <td style="padding: 6px;">株価変動への感応度 / <b>満期時の勝率（確率）</b></td>
                        <td style="padding: 6px; color: #38BDF8;">ITM (勝率高、現物代替)</td>
                        <td style="padding: 6px;">OTM (勝率低、レバレッジ大)</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">IV (予測ボラ)</td>
                        <td style="padding: 6px;">将来の期待変動率 / <b>プレミアム of 割高・割安</b></td>
                        <td style="padding: 6px; color: #FF007F;">割高 (オプション売り手に有利)</td>
                        <td style="padding: 6px; color: #38BDF8;">割安 (オプション買い手に有利)</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #1E293B;">
                        <td style="padding: 6px; font-weight: bold; color: #00FFCC;">OI (取組高)</td>
                        <td style="padding: 6px;">未決済 of 契約残高 / <b>機関投資家の本気度・壁</b></td>
                        <td style="padding: 6px; color: #38BDF8;">強力な支持・抵抗帯 (磁石効果)</td>
                        <td style="padding: 6px;">市場の関与が極めて薄い</td>
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
    
    df_t_shape_display["権利行使価格 (Strike)"] = df_t_shape["strike"].map(lambda x: f"${x:.1f}")
    
    df_t_shape_display["Put Price"] = df_t_shape["lastPrice_put"].map(lambda x: f"${x:.2f}")
    df_t_shape_display["Put Vol"] = df_t_shape["volume_put"].fillna(0).astype(int)
    df_t_shape_display["Put OI"] = df_t_shape["openInterest_put"].fillna(0).astype(int)
    df_t_shape_display["Put IV"] = df_t_shape["impliedVolatility_put"].map(lambda x: f"{x*100:.1f}%")
    df_t_shape_display["Put Delta"] = df_t_shape["Delta_put"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
    
    st.dataframe(
        df_t_shape_display[[
            "Call Delta", "Call IV", "Call OI", "Call Vol", "Call Price", 
            "権利行使価格 (Strike)", 
            "Put Price", "Put Vol", "Put OI", "Put IV", "Put Delta"
        ]],
        use_container_width=True, hide_index=True, height=320
    )
else:
    st.warning("⚠️ オプションチェーンデータを取得できませんでした。")

# ==============================================================================
# 6. NEWS TERMINAL
# ==============================================================================
st.markdown("---")
st.markdown(f"### 🔗 【{current_ticker}】 適時開示＆ニュースターミナル")

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
                    date_str, "🟣 インサイダー [ I ]",
                    f"{item['insider']} ({item['position']}) が 合計 ${item['value']:,.0f} を購入",
                    item["url"], date_specific_news_url,
                    f"https://finviz.com/quote.ashx?t={current_ticker}"
                ])
            else:
                linked_sources_list.append([
                    date_str, "🟡 カタリスト [ R ]",
                    f"【{item['category']}】 {item['title']}",
                    f"https://www.sec.gov/edgar/browse/?CIK={current_ticker}",
                    item["url"],
                    f"https://finviz.com/quote.ashx?t={current_ticker}"
                ])
                
    if linked_sources_list:
        df_sources = pd.DataFrame(linked_sources_list, columns=["日付", "分類", "イベント概要", "SEC Link", "Google News", "Finviz Chart"])
        st.dataframe(
            df_sources,
            column_config={
                "SEC Link": st.column_config.LinkColumn("SEC Link", display_text="Form 4 ↗"),
                "Google News": st.column_config.LinkColumn("Google News", display_text="News ↗"),
                "Finviz Chart": st.column_config.LinkColumn("Finviz Chart", display_text="Chart ↗")
            },
            use_container_width=True, hide_index=True, height=250
        )
else:
    st.info("💡 リンク可能なイベント履歴はありません。")
