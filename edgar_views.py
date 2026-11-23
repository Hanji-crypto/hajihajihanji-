"""EDGAR（Form 4）だけで成り立つ表示部品。edgar_only モードの各ページで使う。

単価・金額は Form 4 に書かれた値（内部者の取引価格）で、市場の株価ではない。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

FORM4_PRICE_NOTE = "単価・金額は Form 4 に記載された内部者の取引価格で、市場の株価ではありません。"


def insider_trades_table(df: pd.DataFrame) -> pd.DataFrame:
    """標準の列（filing_date, buy_date, insider, position, shares, price, value, filing_url）→ 表示用の表。"""
    out = df.copy()
    for c in ("filing_date", "buy_date"):
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out = out.sort_values(["filing_date", "buy_date"], ascending=False)
    return out.rename(columns={
        "filing_date": "提出日", "buy_date": "取引日", "insider": "内部者", "position": "役職",
        "shares": "株数", "price": "取得単価 ($)", "value": "金額 ($)", "filing_url": "出典（EDGAR）",
    })[["提出日", "取引日", "内部者", "役職", "株数", "取得単価 ($)", "金額 ($)", "出典（EDGAR）"]].reset_index(drop=True)


def render_insider_trades(df: pd.DataFrame, title: str, height: int = 320) -> None:
    st.markdown(f"**{title}**")
    st.caption(FORM4_PRICE_NOTE)
    if df.empty:
        st.info("この銘柄の Form 4 の取引はありません。")
        return
    st.dataframe(
        insider_trades_table(df),
        hide_index=True, width="stretch", height=min(height, 35 * (len(df) + 1) + 3),  # 行が少ない時に空行を出さない
        column_config={
            "提出日": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "取引日": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "株数": st.column_config.NumberColumn(format="localized"),
            "取得単価 ($)": st.column_config.NumberColumn(format="dollar"),
            "金額 ($)": st.column_config.NumberColumn(format="dollar"),
            "出典（EDGAR）": st.column_config.LinkColumn("出典（EDGAR）", display_text="書類を開く"),
        },
    )
