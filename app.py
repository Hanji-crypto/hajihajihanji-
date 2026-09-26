import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math

# 独自モジュールから関数をインポート
from data_loader import (
    load_and_process_data,
    generate_screener,
    fetch_market_data,
    compute_technical_indicators,
    fetch_option_chain_by_expiry,
    calculate_volatility_skew
)
from charts import (
    draw_stock_chart,
    draw_sub_indicators_chart,
    draw_volatility_chart,
    draw_payoff_chart
)
from guide_renderer import render_market_diagnostic_and_guide

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
top_10_tickers = df_screener["ticker"].head(10).tolist() if not df_screener.empty else []
all_available_tickers = df_screener["ticker"].tolist() if not df_screener.empty else []

if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = "SMMT" if "SMMT" in all_available_tickers else (top_10_tickers[0] if top_10_tickers else "")
    
if "custom_tickers" not in st.session_state:
    st.session_state.custom_tickers = []

# ==============================================================================
# 3. MAIN TERMINAL LAYOUT
# ==============================================================================
st.title("Whale-Eye: Option and Insider Intelligence")
st.markdown("---")

st.subheader("[スクリーナー] 全銘柄多次元スクリーニング・マトリックス")
col_sel1, col_sel2 = st.columns([4, 8])

with col_sel1:
    search_options = all_available_tickers.copy()
    for ct in st.session_state.custom_tickers:
        if ct not in search_options:
            search_options.append(ct)
    if st.session_state.selected_ticker not in search_options:
        search_options.append(st.session_state.selected_ticker)

    selected_from_dropdown = st.selectbox(
        "解析・表示する銘柄を選択:",
        options=search_options,
        index=search_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in search_options else 0
    )
    if selected_from_dropdown != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_from_dropdown
        st.rerun()

with col_sel2:
    radio_options = list(top_10_tickers)
    if st.session_state.selected_ticker not in radio_options:
        radio_options.append(st.session_state.selected_ticker)
    selected_by_radio = st.radio(
        "クイック選択:",
        options=radio_options,
        index=radio_options.index(st.session_state.selected_ticker) if st.session_state.selected_ticker in radio_options else 0,
        horizontal=True,
        key="ticker_radio"
    )
    if selected_by_radio != st.session_state.selected_ticker:
        st.session_state.selected_ticker = selected_by_radio
        st.rerun()

current_ticker = st.session_state.selected_ticker

if not df_screener.empty:
    df_screener_display = df_screener.copy()
    df_screener_display = df_screener_display.rename(columns={
        "ticker": "ティッカー", "company": "企業名", 
        "net_flow": "ネット・フロー ($)", "total_buy": "総買い額 ($)", "total_sell": "総売り額 ($)",
        "avg_price": "平均取得単価 ($)", "insider": "主なインサイダー", "buy_date": "直近取引日",
        "trade_count": "取引回数", "Certainty (%)": "統計的確実性スコア (%)"
    })
    df_screener_display["ネット・フロー ($)"] = df_screener_display["ネット・フロー ($)"].map(lambda x: f"${x:+,.0f}" if x != 0 else "$0")
    df_screener_display["総買い額 ($)"] = df_screener_display["総買い額 ($)"].map(lambda x: f"${x:,.0f}")
    df_screener_display["総売り額 ($)"] = df_screener_display["総売り額 ($)"].map(lambda x: f"${x:,.0f}")
    df_screener_display["平均取得単価 ($)"] = df_screener_display["平均取得単価 ($)"].map(lambda x: f"${x:.2f}" if pd.notna(x) else "N/A")
    df_screener_display["直近取引日"] = df_screener_display["直近取引日"].dt.strftime('%Y-%m-%d')
    df_screener_display["統計的確実性スコア (%)"] = df_screener_display["統計的確実性スコア (%)"].map(lambda x: f"{x:.1f}%")

    st.dataframe(
        df_screener_display[["ティッカー", "企業名", "ネット・フロー ($)", "総買い額 ($)", "総売り額 ($)", "平均取得単価 ($)", "主なインサイダー", "直近取引日", "取引回数", "統計的確実性スコア (%)"]],
        use_container_width=True, hide_index=True, height=240
    )

st.markdown("---")

# ==============================================================================
# 4. REALTIME ANALYSIS & CHARTS
# ==============================================================================
st.subheader(f"[{current_ticker}] リアルタイム詳細・オプション解析")

period_col1, period_col2 = st.columns([4, 8])
with period_col1:
    selected_period = st.selectbox(
        "データ取得（ヒストリカル）期間:",
        options=["3mo", "6mo", "1y", "2y"], index=1,
        format_func=lambda x: {"3mo": "3ヶ月 (短期)", "6mo": "6ヶ月 (中期・標準)", "1y": "1年間 (長期)", "2y": "2年間 (超長期)"}[x]
    )

with st.spinner(f"[{current_ticker}] の市場データを解析中..."):
    raw_hist, current_price, hv, available_expiries = fetch_market_data(current_ticker, period=selected_period)

if raw_hist is not None and current_ticker not in all_available_tickers and current_ticker not in st.session_state.custom_tickers:
    st.session_state.custom_tickers.append(current_ticker)

if raw_hist is not None:
    hist_data = compute_technical_indicators(raw_hist)
    recommendations_list = []
    
    if available_expiries:
        for expiry in available_expiries:
            try:
                df_calls_raw, df_puts_raw, iv, pcr = fetch_option_chain_by_expiry(current_ticker, expiry, current_price)
                skew_val, skew_status = calculate_volatility_skew(df_calls_raw, df_puts_raw, current_price)
                
                try:
                    expiry_date = datetime.strptime(expiry, "%Y-%m-%d")
                    dte = max(1, (expiry_date - datetime.now()).days)
                except:
                    dte = 30
                
                t_years = dte / 365.25
                expected_move_pct = iv * np.sqrt(t_years)
                
                bc_buy_strike = round(current_price * 0.95, 1)
                bc_sell_strike = round(current_price * (1 + expected_move_pct * 0.7), 1)
                bc_buy_prem = round(current_price * (0.05 + expected_move_pct * 0.3), 2)
                bc_sell_prem = round(current_price * (0.01 + expected_move_pct * 0.1), 2)
                
                cc_buy_stock = current_price
                cc_sell_strike = round(current_price * (1 + expected_move_pct * 0.5), 1)
                cc_sell_prem = round(current_price * (0.02 + expected_move_pct * 0.2), 2)
                
                lc_strike = round(current_price * (1 + expected_move_pct * 0.3), 1)
                lc_prem = round(current_price * (0.01 + expected_move_pct * 0.4), 2)
                
                atm_call_price = current_price * (0.02 + expected_move_pct * 0.3)
                atm_put_price = current_price * (0.02 + expected_move_pct * 0.3)
                
                if not df_calls_raw.empty:
                    df_calls_raw["diff"] = (df_calls_raw["strike"] - current_price).abs()
                    atm_call = df_calls_raw.sort_values(by="diff").iloc[0]
                    atm_call_price = atm_call["lastPrice"] if atm_call["lastPrice"] > 0 else atm_call_price
                    
                    calls_itm = df_calls_raw[df_calls_raw["Delta"].between(0.60, 0.75)]
                    if calls_itm.empty:
                        calls_itm = df_calls_raw[df_calls_raw["strike"] < current_price]
                    calls_otm = df_calls_raw[df_calls_raw["Delta"].between(0.25, 0.40)]
                    if calls_otm.empty:
                        calls_otm = df_calls_raw[df_calls_raw["strike"] >= current_price * 1.10]

                    if not calls_itm.empty and not calls_otm.empty:
                        best_itm = calls_itm.sort_values(by="openInterest", ascending=False).iloc[0]
                        potential_otms = calls_otm[calls_otm["strike"] > best_itm["strike"]]
                        if not potential_otms.empty:
                            best_otm = potential_otms.sort_values(by="openInterest", ascending=False).iloc[0]
                            bc_buy_strike = best_itm["strike"]
                            bc_sell_strike = best_otm["strike"]
                            bc_buy_prem = best_itm["lastPrice"] if best_itm["lastPrice"] > 0 else (current_price - bc_buy_strike)
                            bc_sell_prem = best_otm["lastPrice"] if best_otm["lastPrice"] > 0 else (current_price * 0.02)

                    cc_calls = df_calls_raw[df_calls_raw["Delta"].between(0.15, 0.25)]
                    if cc_calls.empty:
                        cc_calls = df_calls_raw[df_calls_raw["strike"] > current_price]
                    if not cc_calls.empty:
                        best_cc_call = cc_calls.sort_values(by="openInterest", ascending=False).iloc[0]
                        cc_sell_strike = best_cc_call["strike"]
                        cc_sell_prem = best_cc_call["lastPrice"] if best_cc_call["lastPrice"] > 0 else (current_price * 0.03)

                    lc_calls = df_calls_raw[df_calls_raw["Delta"].between(0.45, 0.55)]
                    if lc_calls.empty:
                        lc_calls = df_calls_raw.copy()
                    if not lc_calls.empty:
                        lc_calls["diff"] = (lc_calls["strike"] - current_price).abs()
                        best_lc_call = lc_calls.sort_values(by="diff").iloc[0]
                        lc_strike = best_lc_call["strike"]
                        lc_prem = best_lc_call["lastPrice"] if best_lc_call["lastPrice"] > 0 else (current_price * 0.05)

                if not df_puts_raw.empty:
                    df_puts_raw["diff"] = (df_puts_raw["strike"] - current_price).abs()
                    atm_put = df_puts_raw.sort_values(by="diff").iloc[0]
                    atm_put_price = atm_put["lastPrice"] if atm_put["lastPrice"] > 0 else atm_put_price

                bc_net_cost = max(0.10, bc_buy_prem - bc_sell_prem)
                bc_max_profit = max(0.10, (bc_sell_strike - bc_buy_strike) - bc_net_cost)
                bc_roi = (bc_max_profit / bc_net_cost) * 100
                bc_prob = 50.0 + (15.0 * math.tanh(dte / 90)) + (10.0 if iv > hv else -5.0) + (-5.0 if skew_val > 5.0 else 5.0)

                cc_net_cost = max(1.0, cc_buy_stock - cc_sell_prem)
                cc_max_profit = (cc_sell_strike - cc_buy_stock) + cc_sell_prem
                cc_roi = ((cc_max_profit / cc_net_cost) * 100) * (30 / dte)
                cc_prob = 90.0 - (20.0 * math.tanh(dte / 180)) + (5.0 if iv > hv else 0.0) + (5.0 if skew_val > 3.0 else -5.0)

                lc_roi = 100.0 + (150.0 * math.log10(dte + 1)) + (50.0 if iv < hv else -30.0)
                lc_prob = 40.0 - (15.0 * math.tanh(dte / 120)) + (10.0 if iv < hv else -10.0) + (10.0 if skew_val < -2.0 else -5.0)

                bc_roi = float(np.clip(bc_roi, 5.0, 300.0)) if not np.isnan(bc_roi) else 100.0
                bc_prob = float(np.clip(bc_prob, 10.0, 95.0)) if not np.isnan(bc_prob) else 80.0
                cc_roi = float(np.clip(cc_roi, 1.0, 100.0)) if not np.isnan(cc_roi) else 15.0
                cc_prob = float(np.clip(cc_prob, 20.0, 98.0)) if not np.isnan(cc_prob) else 80.0
                lc_roi = float(np.clip(lc_roi, 10.0, 500.0)) if not np.isnan(lc_roi) else 120.0
                lc_prob = float(np.clip(lc_prob, 5.0, 80.0)) if not np.isnan(lc_prob) else 30.0

                recommendations_list.append({
                    "満期日": expiry, "ATM Strike": round(current_price, 1), "Call Price": atm_call_price, "Put Price": atm_put_price,
                    "ブル・コール ROI (%)": bc_roi, "ブル・コール 勝率 (%)": bc_prob,
                    "カバード・コール ROI (%)": cc_roi, "カバード・コール 勝率 (%)": cc_prob,
                    "ロング・コール ROI (%)": lc_roi, "ロング・コール 勝率 (%)": lc_prob,
                    "IV (%)": iv * 100, "PCR": pcr, "スキュー": skew_val
                })
            except Exception as e:
                continue

    selected_expiry = None
    if available_expiries:
        selected_expiry = st.selectbox("詳細チャート表示用のオプション満期日を選択してください:", options=available_expiries, index=0)
    else:
        st.warning("⚠️ この銘柄には現在、有効なオプションチェーンが存在しないか、取得できません。")

    with st.spinner(f"オプションチェーンを解析中..."):
        if selected_expiry:
            df_calls_raw, df_puts_raw, iv, pcr = fetch_option_chain_by_expiry(current_ticker, selected_expiry, current_price)
            skew_val, skew_status = calculate_volatility_skew(df_calls_raw, df_puts_raw, current_price)
        else:
            df_calls_raw, df_puts_raw = pd.DataFrame(), pd.DataFrame()
            iv = hv if hv > 0 else 0.30
            pcr = 1.0
            skew_val, skew_status = 0.0, "判定不可 (シミュレーション)"

    T_30 = 30 / 365.25
    one_sigma_move = current_price * iv * np.sqrt(T_30)
    upper_1sigma = current_price + one_sigma_move
    lower_1sigma = current_price - one_sigma_move
    
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    with m_col1: st.metric("インプライド・ボラティリティ (IV)", f"{iv*100:.1f}%" if selected_expiry else f"{iv*100:.1f}% (HV代用)")
    with m_col2: st.metric("歴史的ボラティリティ (HV)", f"{hv*100:.1f}%")
    with m_col3: st.metric("ボラティリティ・スキュー (歪み)", f"{skew_val:+.1f}%", help=f"状態: {skew_status}")
    with m_col4: st.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}" if selected_expiry else "N/A")
    with m_col5: st.metric("1σ 上昇上限 (30日)", f"${upper_1sigma:.2f}")
    with m_col6: st.metric("1σ 下落下限 (30日)", f"${lower_1sigma:.2f}")

    st.markdown("---")

    # コントロールパネル
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 3, 4])
    with ctrl_col1:
        chart_type = st.radio("表示形式", options=["ローソク足", "折れ線"], horizontal=True)
    with ctrl_col2:
        overlay_indicator = st.selectbox("重ね合わせ指標の選択:", ["Bollinger Bands", "EMA (20/50)", "Ichimoku", "None"])
    with ctrl_col3:
        sub_indicator = st.selectbox("下段サブ指標の選択:", ["RSI + MACD", "ATR (Volatility Range)"])

       # ----------------------------------------------------------------------
    # CHARTS: メイン ＆ サブ ＆ ボラティリティ
    # ----------------------------------------------------------------------
    st.markdown("### テクニカル分析チャート")
    slice_windows = {"3mo": 60, "6mo": 120, "1y": 250, "2y": 500}
    display_window = slice_windows.get(selected_period, 120)
    
    df_plot = hist_data.iloc[-display_window:].copy()
    plot_dates = df_plot.index
    xaxis_range = [plot_dates[0], plot_dates[-1]]

    future_dates = [plot_dates[-1] + timedelta(days=i) for i in range(1, 31)]
    upper_band_curve = [current_price + (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]
    lower_band_curve = [current_price - (current_price * iv * np.sqrt(i / 365.25)) for i in range(1, 31)]

    # 1. メイン株価チャートの描画と出力
    try:
        fig_stock = draw_stock_chart(
            df_plot, 
            chart_type, 
            overlay_indicator, 
            current_price,
            iv,
            future_dates,
            upper_band_curve,
            lower_band_curve,
            xaxis_range
        )
        st.plotly_chart(fig_stock, use_container_width=True)
    except Exception as e:
        st.error(f"メインチャートの描画中にエラーが発生しました: {e}")

    # 2. サブ指標チャート（RSI / MACD）の描画と出力
    try:
        # 引数の不一致によるエラーを防ぐため、安全に呼び出します
        fig_sub = draw_sub_indicators_chart(df_plot, sub_indicator, xaxis_range)
        st.plotly_chart(fig_sub, use_container_width=True)
    except TypeError:
        # もし引数エラーが発生した場合は、引数を調整して再試行
        try:
            fig_sub = draw_sub_indicators_chart(df_plot, sub_indicator)
            st.plotly_chart(fig_sub, use_container_width=True)
        except Exception as e:
            st.error(f"サブ指標チャートの描画に失敗しました: {e}")
    except Exception as e:
        st.error(f"サブ指標チャートの描画中にエラーが発生しました: {e}")

    # 3. ボラティリティチャートの描画と出力
    try:
        # ティッカー変数の安全な取得
        current_ticker_var = locals().get('ticker', locals().get('selected_ticker', ''))
        if not current_ticker_var and 'df_plot' in locals() and 'ticker' in df_plot.columns:
            # df_plotの中にtickerカラムがあればそこから取得
            current_ticker_var = df_plot['ticker'].iloc[0] if not df_plot['ticker'].empty else 'SPY'
        elif not current_ticker_var:
            current_ticker_var = 'SPY'

        # 生データ（df_raw）にtickerカラムがないと言われた場合の対策として、コピーにカラムを追加
        df_raw_safe = hist_data.copy()
        if 'ticker' not in df_raw_safe.columns:
            df_raw_safe['ticker'] = current_ticker_var

        df_plot_safe = df_plot.copy()
        if 'ticker' not in df_plot_safe.columns:
            df_plot_safe['ticker'] = current_ticker_var

        # キーワード引数を使って、安全にマッピングして呼び出します
        fig_vol = draw_volatility_chart(
            df_plot=df_plot_safe,
            hist_data=hist_data,
            display_window=display_window,
            iv=iv,
            hv=hv,
            df_raw=df_raw_safe,
            current_ticker=current_ticker_var,
            xaxis_range=xaxis_range
        )
        st.plotly_chart(fig_vol, use_container_width=True)
    except Exception as e:
        st.error(f"ボラティリティチャートの描画に失敗しました: {e}")
