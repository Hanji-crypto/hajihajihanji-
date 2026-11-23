"""招待制ベータの入口: 招待コードのゲートと、初回の同意画面。

- 招待コードは st.secrets の `invite_codes`（文字列のリスト）に置く。ソースや README には書かない。
  形は .streamlit/secrets.toml.example を参照。
- secrets に `invite_codes` が無い時（ローカル開発・CI）はゲートも同意画面も出さず、今まで通り表示する。
- `invite_codes` があるのに空・不正な形の時は、誰も入れない（閉じる側に倒す）。
- 入れたコードはセッションに覚え、毎回 secrets と照らし直す。secrets からコードを消せば、そのコードの人は次の操作で入口に戻る。
"""
from __future__ import annotations

import hmac
import time
from collections.abc import Sequence

import streamlit as st

from data_status import DISCLAIMER

SECRET_KEY = "invite_codes"
WRONG_CODE_DELAY_SEC = 1.0
_CODE_STATE = "beta_invite_code"
_CONSENT_STATE = "beta_consented"

CONSENT_RESIDENCE = "日本に住んでいます"
CONSENT_NOT_ADVICE = (
    "本アプリは一般的な情報提供のみを目的としており、個別の投資推奨・投資助言ではないことを理解しました"
    "（投資判断は自分の責任で行います）"
)


def configured_invite_codes() -> list[str] | None:
    """secrets の招待コード。キーが無ければ None（ゲート無効）。キーがあれば有効なコードのリスト（空もありうる）。"""
    try:
        if SECRET_KEY not in st.secrets:
            return None
        raw = st.secrets[SECRET_KEY]
    except Exception:  # secrets.toml が無い・読めない
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Sequence):
        return []
    # 引用符を付け忘れた数字（invite_codes = [1234]）も文字列として受け付ける。黙って誰も入れなくなるのを防ぐ。
    codes = [str(c).strip() for c in raw if isinstance(c, (str, int)) and not isinstance(c, bool)]
    return [c for c in codes if c]


def is_valid_code(entered: str | None, codes: list[str]) -> bool:
    """前後の空白を除いて完全一致（大文字・小文字は区別）。比較は時間差の出ない方法で行う。"""
    if not entered:
        return False
    e = entered.strip().encode()
    if not e:
        return False
    ok = False
    for c in codes:
        ok |= hmac.compare_digest(e, c.encode())
    return ok


# 入口（招待コード・同意画面）の配色。各ページ（app.py など）と同じダークテーマにそろえる。
# 各ページの配色はページ側の CSS で付けているため、ページを読み込む前の入口では自前で当てる。
_GATE_CSS = """
<style>
.stApp { background-color: #0B0F19; color: #E2E8F0; }
.stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label, .stApp li { color: #E2E8F0; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #94A3B8 !important; }
hr { border-color: #1E293B !important; }
[data-testid="stForm"] { background-color: #111827; border: 1px solid #1F2937; border-radius: 8px; }
[data-testid="stTextInputRootElement"], [data-testid="stTextInputRootElement"] > div,
.stTextInput input { background-color: #0F172A !important; color: #E2E8F0 !important; border-color: #334155 !important; }
.stTextInput button, .stTextInput svg { color: #94A3B8 !important; background-color: transparent !important; }
.stApp button[kind^="secondary"], .stApp button[kind^="secondary"] p {
  background-color: #111827; color: #E2E8F0 !important; border-color: #00FFCC; }
.stApp button[kind^="secondary"]:hover, .stApp button[kind^="secondary"]:hover p { color: #00FFCC !important; }
.stApp button[kind="primary"], .stApp button[kind="primary"] p {
  background-color: #00FFCC; color: #0B0F19 !important; border-color: #00FFCC; font-weight: bold; }
.stApp button:disabled, .stApp button:disabled p {
  background-color: #1F2937 !important; color: #64748B !important; border-color: #334155 !important; }
[data-testid="stCheckbox"] label p { color: #E2E8F0 !important; }
</style>
"""


def _apply_gate_theme() -> None:
    st.html(_GATE_CSS)


def _render_code_form(codes: list[str]) -> None:
    _apply_gate_theme()
    st.title("🐋 Whale-Eye 招待制ベータ")
    st.write("このベータは招待制です。お知らせした招待コードを入力してください。")
    with st.form("invite_form"):
        entered = st.text_input("招待コード", type="password", key="invite_code_input")
        submitted = st.form_submit_button("入る")
    if submitted:
        if is_valid_code(entered, codes):
            st.session_state[_CODE_STATE] = entered.strip()
            st.rerun()
        time.sleep(WRONG_CODE_DELAY_SEC)  # 総当たりを遅くする（同じ接続での連続試行）
        st.error("招待コードが違います。もう一度お確かめください。")
    if not codes:
        st.info("現在、新しい入場を受け付けていません。")


def _render_consent() -> None:
    _apply_gate_theme()
    st.title("🐋 Whale-Eye をご利用の前に")
    st.write("はじめに、次の2点をご確認ください（このセッションで1回だけ表示します）。")
    st.caption(f"ⓘ {DISCLAIMER}")
    st.caption("このベータでは、保有銘柄・資産額などの個人の情報はお聞きしません。")
    resident = st.checkbox(CONSENT_RESIDENCE, key="consent_resident")
    not_advice = st.checkbox(CONSENT_NOT_ADVICE, key="consent_not_advice")
    if st.button("同意して進む", type="primary", disabled=not (resident and not_advice)):
        st.session_state[_CONSENT_STATE] = True
        st.rerun()
    if not (resident and not_advice):
        st.caption("2つともチェックすると先へ進めます。日本にお住まいでない方は、このベータをご利用いただけません。")


def require_access() -> bool:
    """入口の判定。True ならページ本体を表示してよい。False の時は入口の画面を描いてあるので、呼び出し側で止める。"""
    codes = configured_invite_codes()
    if codes is None:
        return True  # ゲート無効（ローカル開発・CI）
    if not is_valid_code(st.session_state.get(_CODE_STATE), codes):
        st.session_state.pop(_CODE_STATE, None)
        st.session_state.pop(_CONSENT_STATE, None)
        _render_code_form(codes)
        return False
    if not st.session_state.get(_CONSENT_STATE):
        _render_consent()
        return False
    return True
