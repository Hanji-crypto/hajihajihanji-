"""メールからの深いリンク（?ticker=KNOP）を受けて、その銘柄を選んだ状態でページを開く。

- 入口（streamlit_app.py）で、招待コード・同意の画面より前に URL の ticker を読み、セッションに覚える。
  入口の画面を通る間に URL のクエリが消えても、入場後にその銘柄を選んだ状態で開く。
- 入場後に1回だけ app.py の選択（st.session_state.selected_ticker）に入れる。同じリンクのまま
  利用者が別の銘柄を選んでも、上書きし直さない（違う ticker のリンクで来た時だけ入れ直す）。
- ティッカーは data_quality.normalize_ticker で正規化し、形の正しくない値は無視する。
"""
from __future__ import annotations

import streamlit as st

from data_quality import normalize_ticker

QUERY_KEY = "ticker"
_PENDING = "deep_link_pending_ticker"
_APPLIED = "deep_link_applied_ticker"
SELECTED = "selected_ticker"  # app.py の選択中の銘柄
_WIDGET_KEYS = ("ticker_radio",)  # 前の選択を覚えている app.py のウィジェット


def remember_from_query() -> str | None:
    """URL の ?ticker= を読み、まだ反映していなければ覚える。覚えたティッカーを返す。"""
    try:
        raw = st.query_params.get(QUERY_KEY)
    except Exception:
        raw = None
    ticker = normalize_ticker(raw)
    if ticker and ticker != st.session_state.get(_APPLIED):
        st.session_state[_PENDING] = ticker
    return st.session_state.get(_PENDING)


def apply_pending() -> str | None:
    """入場後に呼ぶ。覚えたティッカーを選択中の銘柄にする。反映したティッカーを返す。"""
    ticker = st.session_state.pop(_PENDING, None)
    if not ticker:
        return None
    st.session_state[SELECTED] = ticker
    for key in _WIDGET_KEYS:
        st.session_state.pop(key, None)
    st.session_state[_APPLIED] = ticker
    return ticker
