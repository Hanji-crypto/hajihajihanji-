import streamlit as st
import pandas as pd
import numpy as np

# ==============================================================================
# オプション推奨戦略セクションの修正コード
# ==============================================================================

st.header("🎯 オプション推奨戦略（全満期日一覧）")

# 1. 選択された満期日（selected_expiries）の安全な定義・取得
# もしUI側で 'selected_expiries' が定義されていない場合のフォールバック
if 'selected_expiries' not in locals() and 'selected_expiries' not in globals():
    # ユーザーが選択した期間、またはデフォルトの期間を設定
    # ※UIに期間選択のマルチセレクト等がある場合はそれを優先します
    selected_expiries = ["3ヶ月", "6ヶ月", "1年", "2年"]
else:
    # 既に定義されている場合はそれを使用
    if not selected_expiries:
        selected_expiries = ["3ヶ月", "6ヶ月", "1年", "2年"]

# 2. 推奨データを格納するリストを確実に初期化 (NameError防止)
recommendations = []

# 3. データのシミュレーションおよび計算処理
# (※実際の yfinance や計算ロジックに合わせて適宜内部を調整してください)
for expiry in selected_expiries:
    try:
        # --- ここで各満期日における戦略を計算 ---
        # 本来の計算ロジック（例: iv, delta, strike の取得）をここに記述します。
        # 以下は、エラーを防ぎつつ動的な値を生成するデモ/フォールバックロジックです。
        
        # 銘柄の現在値（定義されていない場合はデフォルト $150.0）
        current_price = locals().get('current_price', 150.0)
        
        # 満期日に応じた仮の計算（実際の実装に合わせて書き換えてください）
        if "3ヶ月" in expiry:
            strategy_name = "ブル・コール・スプレッド"
            strike_price = round(current_price * 1.05, 2)
            premium = round(current_price * 0.04, 2)
            iv_value = 0.35  # 35%
            delta_value = 0.42
            strategy_score = 85
        elif "6ヶ月" in expiry:
            strategy_name = "カバード・コール"
            strike_price = round(current_price * 1.10, 2)
            premium = round(current_price * 0.06, 2)
            iv_value = 0.38  # 38%
            delta_value = 0.35
            strategy_score = 78
        elif "1年" in expiry:
            strategy_name = "ロング・コール"
            strike_price = round(current_price * 1.15, 2)
            premium = round(current_price * 0.09, 2)
            iv_value = 0.45  # 45%
            delta_value = 0.30
            strategy_score = 92
        else:  # 2年など
            strategy_name = "ロング・コール"
            strike_price = round(current_price * 1.25, 2)
            premium = round(current_price * 0.15, 2)
            iv_value = 0.52  # 52%
            delta_value = 0.25
            strategy_score = 80

        # リストへ追加
        recommendations.append({
            "満期日": expiry,
            "推奨戦略": strategy_name,
            "権利行使価格 ($)": strike_price,
            "プレミアム ($)": premium,
            "インプライド・ボラティリティ (IV)": iv_value,
            "デルタ (Δ)": delta_value,
            "戦略スコア": strategy_score
        })
    except Exception as e:
        # 個別の計算エラーが発生しても、ループを止めずに次に進む
        continue

# 4. DataFrameの作成 (NameErrorは絶対に発生しません)
opt_df = pd.DataFrame(recommendations)

# 5. データバーを
