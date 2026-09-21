import plotly.graph_objects as gr
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import math

def draw_stock_chart(df_plot, chart_type, overlay_indicator, current_price, iv, future_dates, upper_band_curve, lower_band_curve, xaxis_range):
    """
    1段目：株価チャートのみを完全に独立して描画する関数。
    RSIやMACDのデータは一切ここに関与しないため、混入は物理的に発生しません。
    """
    fig = gr.Figure()

    # 株価トレース
    if chart_type == "ローソク足":
        fig.add_trace(gr.Candlestick(
            x=df_plot.index, open=df_plot["Open"], high=df_plot["High"], low=df_plot["Low"], close=df_plot["Close"], name="株価"
        ))
    else:
        fig.add_trace(gr.Scatter(
            x=df_plot.index, y=df_plot["Close"], mode="lines", line=dict(color="#00FFCC", width=2.5), name="現物株価"
        ))

    # テクニカル指標の重ね合わせ (fill='none' で塗りつぶしバグを完全排除)
    if overlay_indicator == "ボリンジャーバンド" and "BB_Upper" in df_plot.columns:
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["BB_Upper"], line=dict(color="rgba(0, 255, 204, 0.35)", width=1.0, dash="dash"), fill='none', name="BB Upper"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["BB_Lower"], line=dict(color="rgba(0, 255, 204, 0.35)", width=1.0, dash="dash"), fill='none', name="BB Lower"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MA20"], line=dict(color="orange", width=1.0, dash="dot"), fill='none', name="20日移動平均"))
    elif overlay_indicator == "EMA (20/50)":
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#00C5FF", width=1.2), fill='none', name="EMA 20"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["EMA50"], line=dict(color="#FF8C00", width=1.2), fill='none', name="EMA 50"))
    elif overlay_indicator == "一目均衡表 (Ichimoku)":
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Senkou_Span_A"], line=dict(color="rgba(56, 189, 248, 0.4)", width=0.8, dash="dash"), fill='none', name="先行スパンA"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Senkou_Span_B"], line=dict(color="rgba(244, 63, 94, 0.4)", width=0.8, dash="dash"), fill='none', name="先行スパンB"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Tenkan_Sen"], line=dict(color="#38BDF8", width=1.0), fill='none', name="転換線"))
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["Kijun_Sen"], line=dict(color="#F43F5E", width=1.0), fill='none', name="基準線"))

    # 1σ予測レンジ
    fig.add_trace(gr.Scatter(x=future_dates, y=upper_band_curve, mode="lines", line=dict(color="rgba(56, 189, 248, 0.6)", width=1.2, dash="dash"), fill='none', name="1σ上限"))
    fig.add_trace(gr.Scatter(x=future_dates, y=lower_band_curve, mode="lines", line=dict(color="rgba(239, 68, 68, 0.6)", width=1.2, dash="dash"), fill='none', name="1σ下限"))

    fig.update_layout(
        height=380, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
        dragmode="drawline", newshape=dict(line=dict(color="#00FFCC", width=1.5), opacity=0.8),
        xaxis=dict(range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
        yaxis=dict(title="株価 ($)", showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)")
    )
    return fig

def draw_sub_indicators_chart(df_plot, sub_indicator, xaxis_range):
    """
    2段目：サブ指標（RSI, MACD, ATR）のみを完全に独立して描画する関数。
    株価のローソク足トレースは一切インポートすらしていないため、混入バグは100%発生しません。
    """
    if sub_indicator == "RSI + MACD":
        # RSIとMACDの2段サブプロット
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_width=[0.5, 0.5])
        
        # RSI (Row 1)
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["RSI_14"], mode="lines", line=dict(color="#A855F7", width=2.0), fill='none', name="RSI"), row=1, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(239, 68, 68, 0.5)", row=1, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 204, 0.5)", row=1, col=1)

        # MACD (Row 2)
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MACD"], mode="lines", line=dict(color="#38BDF8", width=1.5), fill='none', name="MACD"), row=2, col=1)
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["MACD_Signal"], mode="lines", line=dict(color="#FF8C00", width=1.5), fill='none', name="Signal"), row=2, col=1)
        
        hist_colors = ["#00FFCC" if (not math.isnan(val) and val >= 0) else "#FF007F" for val in df_plot["MACD_Hist"]]
        fig.add_trace(gr.Bar(x=df_plot.index, y=df_plot["MACD_Hist"], marker_color=hist_colors, name="Hist"), row=2, col=1)
        
        fig.update_layout(
            height=280, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
            margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
            xaxis=dict(range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            xaxis2=dict(title="日付", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            yaxis=dict(title="RSI", range=[10, 90]),
            yaxis2=dict(title="MACD")
        )
    else:
        # ATR単体グラフ
        fig = gr.Figure()
        fig.add_trace(gr.Scatter(x=df_plot.index, y=df_plot["ATR"], mode="lines", line=dict(color="#E2E8F0", width=1.8), fill='none', name="ATR"))
        
        fig.update_layout(
            height=180, template="plotly_dark", paper_bgcolor="#0B0F19", plot_bgcolor="#0B0F19",
            margin=dict(l=10, r=10, t=10, b=10), showlegend=False, hovermode="x unified",
            xaxis=dict(title="日付", range=xaxis_range, showspikes=True, spikemode="across", spikethickness=1, spikedash="dash", spikecolor="rgba(255, 255, 255, 0.4)"),
            yaxis=dict(title="ATR")
        )
    return fig
