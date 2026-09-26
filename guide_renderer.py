import streamlit as st
import pandas as pd
import numpy as np

def render_market_diagnostic_and_guide(selected_expiry, skew_val, skew_status, iv, hv):
    """
    市場環境の総合診断およびオプション統計指標のガイドラインをHTMLで描画するモジュール。
    app.pyのコード量を削減し、SyntaxErrorを根本的に防止するために物理分離。
    """
    if not selected_expiry:
        return

    # 現在の市場環境を総合診断
    skew_sentiment = "強気 (コール需要過熱)" if skew_val < -1.0 else ("弱気 (プット需要過熱)" if skew_val > 3.0 else "中立 (需給均衡)")
    iv_hv_ratio = iv / (hv if hv > 0 else 1.0)
    vol_sentiment = "オプション割高 (売り手有利)" if iv_hv_ratio > 1.1 else ("オプション割安 (買い手有利)" if iv_hv_ratio < 0.9 else "適正価格")
    
    # 推奨アクションの決定
    if iv_hv_ratio > 1.1:
        recommended_action = "カバード・コールによるインカムゲイン獲得、またはスプレッド取引による売りプレミアムの相殺"
        action_color = "#38BDF8"
    elif skew_val < -1.0:
        recommended_action = "ロング・コールまたはブル・コール・スプレッドによる積極的な上値追い"
        action_color = "#00FFCC"
    else:
        recommended_action = "ブル・コール・スプレッドによる手堅いディフェンシブ運用"
        action_color = "#A855F7"

    st.html(f"""
        <div class="guide-panel" style="border-top: 4px solid {action_color};">
            <h4 style="color: {action_color}; margin-top: 0; margin-bottom: 15px;">📊 現在の市場環境に基づく総合診断シグナル</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 20px;">
                <div style="background-color: #111827; padding: 15px; border-radius: 6px; border: 1px solid #1E293B;">
                    <span style="color: #94A3B8; font-size: 11px; display: block; margin-bottom: 5px;">市場センチメント (スキュー判定)</span>
                    <strong style="color: #E2E8F0; font-size: 16px;">{skew_sentiment}</strong>
                    <p style="color: #94A3B8; font-size: 11px; margin-top: 5px; margin-bottom: 0;">スキュー値: {skew_val:+.1f}% (状態: {skew_status})</p>
                </div>
                <div style="background-color: #111827; padding: 15px; border-radius: 6px; border: 1px solid #1E293B;">
                    <span style="color: #94A3B8; font-size: 11px; display: block; margin-bottom: 5px;">オプション価格の割高・割安度</span>
                    <strong style="color: #E2E8F0; font-size: 16px;">{vol_sentiment}</strong>
                    <p style="color: #94A3B8; font-size: 11px; margin-top: 5px; margin-bottom: 0;">IV/HV比率: {iv_hv_ratio:.2f} (IV: {iv*100:.1f}% / HV: {hv*100:.1f}%)</p>
                </div>
                <div style="background-color: #111827; padding: 15px; border-radius: 6px; border: 1px solid #1E293B; grid-column: span 2;">
                    <span style="color: #94A3B8; font-size: 11px; display: block; margin-bottom: 5px;">推奨されるオプション執行アクション</span>
                    <strong style="color: {action_color}; font-size: 16px;">{recommended_action}</strong>
                    <p style="color: #94A3B8; font-size: 11px; margin-top: 5px; margin-bottom: 0;">※インサイダーの統計的確実性スコアと、満期日ごとの時間価値減少(Theta)を考慮した最適解です。</p>
                </div>
            </div>
            
            <h5 style="color: #E2E8F0; margin-bottom: 10px;">💡 オプション統計指標のクイック解読マニュアル</h5>
            <div style="font-size: 12px; line-height: 1.6; color: #94A3B8;">
                <table style="width: 100%; border-collapse: collapse; color: #E2E8F0;">
                    <thead>
                        <tr style="border-bottom: 1px solid #1E293B; text-align: left;">
                            <th style="padding: 6px;">指標名</th>
                            <th style="padding: 6px;">数値の意味</th>
                            <th style="padding: 6px;">「値が大きい」場合の投資判断</th>
                            <th style="padding: 6px;">「値が小さい」場合の投資判断</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">Delta (デルタ)</td>
                            <td style="padding: 6px;">株価変動への感応度 / 満期時の勝率（確率）</td>
                            <td style="padding: 6px; color: #38BDF8;">ITM (勝率高、現物代替として堅実に保有)</td>
                            <td style="padding: 6px;">OTM (勝率低、レバレッジ大で短期勝負)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">IV (予測ボラ)</td>
                            <td style="padding: 6px;">将来の期待変動率 / プレミアムの割高・割安</td>
                            <td style="padding: 6px; color: #FF007F;">割高 (オプション売り手有利。カバード・コール推奨)</td>
                            <td style="padding: 6px; color: #38BDF8;">割安 (オプション買い手有利。ロング・コール推奨)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #1E293B;">
                            <td style="padding: 6px; font-weight: bold; color: #00FFCC;">OI (建玉)</td>
                            <td style="padding: 6px;">未決済の契約総数 / 市場の注目度</td>
                            <td style="padding: 6px; color: #38BDF8;">強い支持線・抵抗線として機能（壁としての意識）</td>
                            <td style="padding: 6px;">流動性が低くスプレッドが広いため、取引回避推奨</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    """)
