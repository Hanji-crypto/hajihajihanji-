"""データモード（どのデータ源を使うか）を1か所で決める。

- st.secrets の `data_mode` に "edgar_only" か "full" を置く。
- 置いていない時の既定:
    - 招待コードのゲートが有効（secrets に invite_codes がある）= 招待制ベータ → "edgar_only"
    - ゲートが無い（ローカル開発・CI）→ "full"
- 不正な値の時は "edgar_only"（株価を出さない側＝閉じる側に倒す）。

edgar_only では SEC EDGAR の公式開示だけを使い、Yahoo Finance（yfinance）は import も呼び出しもしない。
yfinance を使うコードは、full の時だけ関数の中で import する（data_loader.py などを参照）。
"""
from __future__ import annotations

import streamlit as st

SECRET_KEY = "data_mode"
EDGAR_ONLY = "edgar_only"
FULL = "full"
MODES = (EDGAR_ONLY, FULL)


def get_data_mode() -> str:
    from access_gate import configured_invite_codes

    try:
        raw = st.secrets[SECRET_KEY] if SECRET_KEY in st.secrets else None
    except Exception:  # secrets.toml が無い・読めない
        raw = None
    if raw is None:
        return EDGAR_ONLY if configured_invite_codes() is not None else FULL
    value = str(raw).strip().lower()
    return value if value in MODES else EDGAR_ONLY


def is_edgar_only() -> bool:
    return get_data_mode() == EDGAR_ONLY
