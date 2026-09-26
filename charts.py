import plotly.graph_objects as gr
import numpy as np
from datetime import timedelta

def draw_stock_chart(df_plot, chart_type, overlay_indicator, current_price, iv, future_dates, upper_band_curve, lower_band_curve, xaxis_range):
    """メイン株価チャートを描画"""
    fig = gr.Figure()
    
    # 1σ 確率予測範囲 (30日) の網掛け
    fig.add_trace(gr.Scatter(
        x=list(future_dates) + list(future_dates)[::-1],
        y=list(upper_band_curve) + list(lower_band_curve)[::-1],
        fill='toself',
        fillcolor='rgba(56, 189, 248, 0.08)',
        line=dict(color='rgba(255,255,255,0)'),
        hoverinfo="skip",
        name="1σ 確率予測範囲 (30日)"
    ))

    if chart_type == "ローソク足":
        fig.add_trace(gr.Candlestick(
            x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'],
            name="株価", increasing_line_color='#00FFCC', decreasing_line_color='#FF007F'
        ))
    else:
        fig.add_trace(gr.Scatter(
            x=df_plot.index, y=df_plot['Close'], mode="lines",
            line=dict(color="#00FFCC", width=2), name="終値"
        ))

    # 重ね合わせ指標
    if overlay_indicator == "Bollinger Bands":
        ma = df_plot['Close'].rolling(window=20).mean()
        std = df_plot['Close'].rolling(window=20).std()
        fig.add_trace(gr.Scatter(x=df_plot.index, y=ma + 2*std, mode="lines", line=dict(color="rgba(148, 163, 184, 0.4)", width=1, dash="dash"), name="BB Upper"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=ma - 2*std, mode="lines", line=dict(color="rgba(148, 163, 184, 0.4)", width=1, dash="dash"), name="BB Lower"))
    elif overlay_indicator == "EMA (20/50)":
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot['Close'].ewm(span=20).mean(), mode="lines", line=dict(color="#38BDF8", width=1), name="EMA 20"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot['Close'].ewm(span=50).mean(), mode="lines", line=dict(color="#A855F7", width=1), name="EMA 50"))

    fig.update_layout(
        height=350, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        xaxis=dict(range=xaxis_range, showgrid=True, gridcolor="rgba(255,255,255,0.05)", rangeslider=dict(visible=False)),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
    )
    return fig

def draw_sub_indicators_chart(df_plot, sub_indicator, xaxis_range):
    """サブ指標（RSI, MACD, ATR）を描画"""
    fig = gr.Figure()
    
    if sub_indicator == "RSI + MACD":
        # RSI (14)
        delta = df_plot['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        
        fig.add_trace(gr.Scatter(x=df_plot.index, y=rsi, mode="lines", line=dict(color="#A855F7", width=1.5), name="RSI (14)"))
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 0, 127, 0.4)", line_width=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 204, 0.4)", line_width=1)
        fig.update_yaxes(range=[10, 90])
    else:
        # ATR
        high_low = df_plot['High'] - df_plot['Low']
        high_close = (df_plot['High'] - df_plot['Close'].shift()).abs()
        low_close = (df_plot['Low'] - df_plot['Close'].shift()).abs()
        ranges = gr.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(14).mean()
        fig.add_trace(gr.Scatter(x=df_plot.index, y=atr, mode="lines", line=dict(color="#FF8C00", width=1.5), name="ATR (14)"))

    fig.update_layout(
        height=150, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        xaxis=dict(range=xaxis_range, showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
    )
    return fig

def draw_volatility_chart(plot_dates, hist_data, display_window, iv, hv, df_raw, current_ticker, xaxis_range):
    """ボラティリティ（IV/HV）歴史的推移 ＆ インサイダータイミングを描画"""
    fig = gr.Figure()
    
    # 20日ヒストリカルボラティリティの算出
    hist_data["HV_20"] = hist_data["Close"].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
    hist_data["IV_Sim"] = hist_data["HV_20"] * (iv / (hv if hv > 0 else 1.0))

    fig.add_trace(gr.Scatter(x=plot_dates, y=hist_data["HV_20"].iloc[-display_window:], mode="lines", line=dict(color="#FF007F", width=1.5), name="HV (%)"))
    fig.add_trace(gr.Scatter(x=plot_dates, y=hist_data["IV_Sim"].iloc[-display_window:], mode="lines", line=dict(color="#00C5FF", width=1.5), name="IV (%)"))

    df_ticker_raw = df_raw[df_raw["ticker"] == current_ticker].copy()
    df_insider_daily = df_ticker_raw.groupby(["buy_date", "insider"])["net_value"].sum().reset_index()
    df_insider_daily = df_insider_daily[df_insider_daily["buy_date"].isin(hist_data.index)]

    if not df_insider_daily.empty:
        unique_insiders = df_insider_daily["insider"].unique().tolist()
        color_palette = ["#AA00FF", "#00FFCC", "#38BDF8", "#FFD700", "#FF007F", "#FF8C00"]
        date_counts = {}
        registered_legends = set()
        
        for _, row in df_insider_daily.iterrows():
            b_date = row["buy_date"]
            insider = row["insider"]
            val = row["net_value"]
            
            if b_date not in date_counts:
                date_counts[b_date] = 0
            else:
                date_counts[b_date] += 1
                
            idx_for_color = unique_insiders.index(insider)
            color = color_palette[idx_for_color % len(color_palette)]
            offset_y = 6.0 - (date_counts[b_date] * 12.0)
            
            symbol = "star" if val > 0 else "triangle-down"
            trade_label = "購入" if val > 0 else "売却"
            hover_text = f"インサイダー: {row['insider']}<br>取引: {trade_label}<br>金額: ${abs(val):,.0f}"
            
            show_in_legend = insider not in registered_legends
            if show_in_legend:
                registered_legends.add(insider)
            
            fig.add_trace(gr.Scatter(
                x=[b_date], y=[offset_y], mode="markers",
                marker=dict(symbol=symbol, size=14, color=color, line=dict(color="#FFFFFF", width=1.2)),
                text=[hover_text], hoverinfo="text", legendgroup=insider, name=f"🐋 {insider} ({trade_label})", showlegend=show_in_legend
            ))
            
    fig.update_layout(
        height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=130, t=50, b=10), 
        legend=dict(orientation="v", y=1, x=1.02, xanchor="left", yanchor="top"),
        xaxis=dict(title="日付", range=xaxis_range, showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="ボラティリティ (%)", range=[-25, 105], showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        hovermode="x unified", hoverlabel=dict(bgcolor="rgba(17, 24, 39, 0.85)", font_size=11, font_family="Consolas, monospace")
    )
    return fig

def draw_payoff_chart(current_price, iv, T_30, payoffs, stock_changes, breakeven_change, breakeven_price, best_strat):
    """アフォーダンスを極限まで高めた損益図（ペイオフ・ダイアグラム）を描画"""
    fig = gr.Figure()
    
    # 1. 利益エリア（緑）と損失エリア（赤）の背景塗り分け
    fig.add_hrect(y0=0, y1=max(payoffs)*1.2 if max(payoffs) > 0 else 100, fillcolor="rgba(0, 255, 204, 0.03)", line_width=0)
    fig.add_hrect(y0=min(payoffs)*1.2 if min(payoffs) < 0 else -100, y1=0, fillcolor="rgba(255, 0, 127, 0.03)", line_width=0)
    
    # 2. 1σ 確率予測範囲の網掛け
    fig.add_vrect(
        x0=-iv*np.sqrt(T_30)*100, x1=iv*np.sqrt(T_30)*100, 
        fillcolor="rgba(56, 189, 248, 0.08)", line_width=0, 
        annotation_text="1σ 確率予測範囲 (30日)", annotation_position="top left", 
        annotation_font=dict(size=10, color="rgba(56, 189, 248, 0.7)")
    )
    
    # 3. 損益曲線のプロット
    fig.add_trace(gr.Scatter(
        x=stock_changes * 100, y=payoffs, mode="lines", 
        line=dict(color="#00FFCC", width=3),
        hovertemplate="株価騰落率: %{x:+.1f}%<br>予想投資リターン: %{y:+.1f}%<extra></hover>"
    ))
    
    # 4. 現在株価 (0%) の縦線
    fig.add_vline(x=0, line_dash="solid", line_color="rgba(255, 255, 255, 0.3)", line_width=1.5, annotation_text="現在株価", annotation_position="bottom right")
    
    # 5. 損益分岐点（Break-even）の縦線表示
    if not np.isnan(breakeven_change):
        fig.add_vline(
            x=breakeven_change, line_dash="dash", line_color="#FF007F", line_width=2,
            annotation_text=f"損益分岐点: {breakeven_change:+.1f}%", annotation_position="top right",
            annotation_font=dict(color="#FF007F", size=11, bold=True)
        )
    
    fig.add_hline(y=0, line_color="rgba(255, 255, 255, 0.5)", line_width=1)
    
    fig.update_layout(
        height=300, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19", 
        margin=dict(l=10, r=10, t=10, b=10), 
        xaxis=dict(title="満期時株価騰落率 (%)", range=[-30, 30], gridcolor="rgba(255, 255, 255, 0.05)"), 
        yaxis=dict(title="予想投資リターン (%)", gridcolor="rgba(255, 255, 255, 0.05)"), 
        showlegend=False
    )
    return fig
