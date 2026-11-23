"""招待コードのゲートと初回の同意画面を AppTest で確かめる。実行: pytest test_access_gate.py

コードは実在しないテスト用の値。株価・SEC への通信は test_smoke_pages の偽物に差し替える。
"""
import pytest
from streamlit.testing.v1 import AppTest

import access_gate as ag
from test_smoke_pages import offline  # noqa: F401  (autouse フィクスチャを読み込む)

CODE = "test-code-123"


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(ag, "WRONG_CODE_DELAY_SEC", 0)


def _app(codes=None):
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    if codes is not None:
        at.secrets["invite_codes"] = codes
    return at.run()


def _texts(at):
    return " ".join(str(e.value) for e in list(at.title) + list(at.caption) + list(at.markdown) + list(at.error) + list(at.info))


def _enter(at, code):
    at.text_input(key="invite_code_input").input(code)
    at.button[0].click()  # フォームの「入る」
    return at.run()


def _consent(at, resident=True, not_advice=True):
    at.checkbox(key="consent_resident").set_value(resident)
    at.checkbox(key="consent_not_advice").set_value(not_advice)
    return at.run()


def _proceed_button(at):
    return next(b for b in at.button if b.label == "同意して進む")


def _is_page_shown(at):
    return len(at.subheader) > 0 and "データの最新提出日" in _texts(at)


def test_no_secrets_shows_pages_as_before():
    at = _app()
    assert not at.exception
    assert _is_page_shown(at)
    assert not at.text_input and "招待制ベータ" not in _texts(at)


def test_gate_blocks_pages_before_code():
    at = _app([CODE])
    assert not at.exception
    assert "招待コード" in _texts(at)
    assert not _is_page_shown(at)
    # 入口でも出典と免責は出る
    assert "U.S. SEC EDGAR" in _texts(at) and "投資助言ではありません" in _texts(at)


@pytest.mark.parametrize("wrong", ["wrong", "", "TEST-CODE-123", "test-code-12"])
def test_wrong_code_is_rejected(wrong):
    at = _enter(_app([CODE]), wrong)
    assert not at.exception
    assert any("招待コードが違います" in e.value for e in at.error)
    assert not _is_page_shown(at)
    assert not at.checkbox  # 同意画面にも進まない


def test_empty_code_list_lets_nobody_in():
    at = _enter(_app([]), "anything")
    assert any("招待コードが違います" in e.value for e in at.error)
    assert not _is_page_shown(at)


def test_numeric_and_single_string_codes_are_accepted():
    # 引用符を付け忘れた数字のコードや、リストでなく1つの文字列でも入れる
    at = _enter(_app([1234]), "1234")
    assert not at.text_input
    at = _enter(_app(CODE), CODE)
    assert not at.text_input


def test_correct_code_then_consent_then_pages():
    at = _enter(_app([CODE, "other"]), f"  {CODE} ")  # 前後の空白は無視する
    assert not at.exception
    assert not at.text_input  # ゲートを抜けた
    assert not _is_page_shown(at)  # まだ同意画面
    assert _proceed_button(at).disabled

    # 片方だけでは進めない
    at = _consent(at, resident=True, not_advice=False)
    assert _proceed_button(at).disabled
    at = _consent(at, resident=False, not_advice=True)
    assert _proceed_button(at).disabled

    at = _consent(at)
    assert not _proceed_button(at).disabled
    _proceed_button(at).click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _is_page_shown(at)
    assert "U.S. SEC EDGAR" in _texts(at)

    # 同じセッションでは同意画面を出さない（ページ移動しても）
    at.switch_page("app_compare_dashboard.py")
    at.run()
    assert not at.exception
    assert not any(c.key == "consent_resident" for c in at.checkbox)
    assert len(at.subheader) > 0


def test_revoked_code_sends_back_to_gate():
    at = _enter(_app([CODE]), CODE)
    at = _consent(at)
    _proceed_button(at).click()
    at.run()
    assert _is_page_shown(at)
    at.secrets["invite_codes"] = ["new-code"]
    at.run()
    assert not _is_page_shown(at)
    assert at.text_input(key="invite_code_input") is not None


def test_is_valid_code_unit():
    assert ag.is_valid_code(CODE, [CODE])
    assert ag.is_valid_code(f" {CODE}\n", [CODE])
    assert not ag.is_valid_code(None, [CODE])
    assert not ag.is_valid_code("   ", [CODE, ""])
    assert not ag.is_valid_code(CODE, [])
    assert not ag.is_valid_code("日本語", [CODE])
    assert ag.is_valid_code("日本語", ["日本語"])
