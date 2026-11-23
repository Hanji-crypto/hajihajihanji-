"""メールからの深いリンク（?ticker=）を AppTest で確かめる。実行: pytest test_deep_link.py

株価・SEC への通信は test_smoke_pages の偽物に差し替える。
"""
import pytest
from streamlit.testing.v1 import AppTest

import access_gate as ag
from test_smoke_pages import offline  # noqa: F401  (autouse フィクスチャを読み込む)

CODE = "test-code-123"
TICKER = "KNOP"  # insider.db にある銘柄


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(ag, "WRONG_CODE_DELAY_SEC", 0)


def _app(ticker=None, codes=None):
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    if codes is not None:
        at.secrets["invite_codes"] = codes
    if ticker is not None:
        at.query_params["ticker"] = ticker
    return at.run()


def _selected(at):
    return at.selectbox[0].value  # app.py の「解析・表示する銘柄を選択」


def _subheaders(at):
    return " ".join(s.value for s in at.subheader)


def test_ticker_query_selects_the_ticker():
    at = _app("knop")  # 小文字でも正規化する
    assert not at.exception, [e.value for e in at.exception]
    assert _selected(at) == TICKER
    assert f"[{TICKER}]" in _subheaders(at)


def test_without_query_default_selection_is_unchanged():
    default = _selected(_app())
    assert _selected(_app("NONE")) == default  # 無効なティッカーは無視
    assert _selected(_app("<script>")) == default


def test_ticker_is_kept_through_invite_code_and_consent():
    at = _app(TICKER, codes=[CODE])
    assert "招待制ベータ" in " ".join(t.value for t in at.title)
    at.query_params.clear()  # 入口の画面の間に URL のクエリが消えても残る
    at.text_input(key="invite_code_input").input(CODE)
    at.button[0].click()
    at.run()
    at.checkbox(key="consent_resident").set_value(True)
    at.checkbox(key="consent_not_advice").set_value(True)
    at.run()
    next(b for b in at.button if b.label == "同意して進む").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _selected(at) == TICKER
    assert f"[{TICKER}]" in _subheaders(at)


def test_user_choice_is_not_overwritten_by_the_same_link():
    at = _app(TICKER)
    other = next(o for o in at.selectbox[0].options if o != TICKER)
    at.selectbox[0].select(other)
    at.run()
    at.run()  # URL に ?ticker=KNOP が残ったままでも
    assert _selected(at) == other


def test_new_link_in_same_session_applies():
    at = _app(TICKER)
    other = next(o for o in at.selectbox[0].options if o != TICKER)
    at.query_params["ticker"] = other
    at.run()
    assert _selected(at) == other
