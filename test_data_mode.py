"""data_mode（データモードの決め方）のテスト。実行: pytest"""
import pytest
import streamlit as st

import data_mode as dm


def _set(**kv):
    st.secrets._secrets = dict(kv)  # conftest の空の secrets に値を入れる


def test_default_without_gate_is_full():
    _set()
    assert dm.get_data_mode() == dm.FULL and not dm.is_edgar_only()


def test_default_with_gate_is_edgar_only():
    _set(invite_codes=["abc"])
    assert dm.get_data_mode() == dm.EDGAR_ONLY and dm.is_edgar_only()


def test_default_with_empty_gate_is_edgar_only():
    _set(invite_codes=[])  # ゲート有効（誰も入れない）でも既定は edgar_only
    assert dm.is_edgar_only()


@pytest.mark.parametrize(
    "secrets, expected",
    [
        ({"data_mode": "full", "invite_codes": ["abc"]}, dm.FULL),  # 明示すればゲートありでも full
        ({"data_mode": "edgar_only"}, dm.EDGAR_ONLY),  # 明示すればゲートなしでも edgar_only
        ({"data_mode": " EDGAR_ONLY "}, dm.EDGAR_ONLY),  # 前後の空白・大文字は許す
        ({"data_mode": "edgar"}, dm.EDGAR_ONLY),  # 不正な値は株価を出さない側に倒す
        ({"data_mode": ""}, dm.EDGAR_ONLY),
    ],
)
def test_explicit_mode(secrets, expected):
    _set(**secrets)
    assert dm.get_data_mode() == expected


def test_edgar_modules_do_not_import_yfinance():
    """edgar_only で使うモジュールは、読み込んだだけでは yfinance を import しない（別プロセスで確かめる）。"""
    import subprocess
    import sys

    code = (
        "import sys, data_mode, data_loader, data_status, data_quality, sec_company, edgar_views, "
        "compare_logic, charts, guide_renderer, access_gate, page_flow, edgar\n"
        "assert 'yfinance' not in sys.modules, 'yfinance was imported'\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
