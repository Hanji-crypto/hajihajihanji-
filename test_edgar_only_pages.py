"""edgar_only（招待制ベータ）の3ページを AppTest で起動するテスト。実行: pytest test_edgar_only_pages.py

- yfinance は import されたら記録して ImportError にする（import も呼び出しもされないことを確かめる）。
- SEC への通信（Submissions API・edgartools の 8-K）は偽物に差し替える。
- 株価・オプション・ボラティリティの部品と Yahoo の出典が画面に出ないこと、インサイダー取引の表が残ることを確かめる。
"""
import importlib.abc
import sqlite3
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import sec_company

PAGES = ["app.py", "app_bi_dashboard.py", "app_compare_dashboard.py"]
PRICE_WORDS = ["オプション", "ボラティリティ", "騰落率", "株価チャート", "テクニカル", "RSI", "リターン", "Yahoo", "yfinance"]


class BlockYfinance(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.attempts = []

    def find_spec(self, name, path=None, target=None):
        if name == "yfinance" or name.startswith("yfinance."):
            self.attempts.append(name)
            raise ImportError("edgar_only では yfinance を読み込まない")
        return None


def _latest_filing():
    (v,) = sqlite3.connect("insider.db").execute("SELECT MAX(filing_date) FROM insider_trades").fetchone()
    return pd.Timestamp(v)


class Fake8KCompany:
    """新しい順に 8-K を返す（提出日の前後）。"""

    def __init__(self, ticker):
        self.ticker = ticker

    def get_filings(self, form):
        base = _latest_filing()
        return [
            SimpleNamespace(filing_date=(base + pd.Timedelta(days=d)).date(), items=items,
                            filing_url=f"https://www.sec.gov/Archives/edgar/data/1/{d}.htm")
            for d, items in [(3, "2.02,9.01"), (-5, "5.02"), (-400, "8.01")]
        ]


@pytest.fixture(autouse=True)
def edgar_only_env(monkeypatch):
    import edgar

    blocker = BlockYfinance()
    monkeypatch.delitem(sys.modules, "yfinance", raising=False)
    for name in [m for m in sys.modules if m.startswith("yfinance.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [blocker] + sys.meta_path)
    sec_calls = []

    def fake_get_json(url, ua):
        sec_calls.append((url, ua))
        return {"sic": "4953", "sicDescription": "Refuse Systems"}

    monkeypatch.setattr(sec_company, "_get_json", fake_get_json)
    monkeypatch.setattr(edgar, "Company", Fake8KCompany)
    st.cache_data.clear()
    yield SimpleNamespace(blocker=blocker, sec_calls=sec_calls)
    st.cache_data.clear()
    assert blocker.attempts == [], f"yfinance が読み込まれようとした: {blocker.attempts}"
    assert "yfinance" not in sys.modules


def _texts(at):
    return " ".join(
        str(e.value)
        for e in list(at.title) + list(at.subheader) + list(at.caption) + list(at.markdown) + list(at.warning)
        + list(at.info)
    )


def _labels(at):
    return " ".join(str(w.label) for w in list(at.selectbox) + list(at.radio) + list(at.checkbox)
                    + list(at.number_input) + list(at.slider) + list(at.select_slider) + list(at.metric))


def _start(page, **secrets):
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    for k, v in secrets.items():
        at.secrets[k] = v
    at.run()
    if page != "app.py":
        at.switch_page(page)
        at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_starts_without_yfinance(page, edgar_only_env):
    at = _start(page, data_mode="edgar_only")
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert len(at.subheader) > 0
    text = _texts(at)
    assert "データの最新提出日" in text and "投資助言ではありません" in text
    assert "出典: U.S. SEC EDGAR" in text  # フッターの出典は SEC だけ
    for word in PRICE_WORDS:
        assert word not in text + _labels(at), f"{page}: 株価に依存する表示が残っている: {word}"
    # インサイダー取引（Form 4）の表と出典リンクは残る
    assert len(at.dataframe) >= 1
    assert "Form 4" in text


def test_insider_table_columns():
    at = _start("app.py", data_mode="edgar_only")
    cols = [list(df.value.columns) for df in at.dataframe]
    assert ["提出日", "取引日", "内部者", "役職", "株数", "取得単価 ($)", "金額 ($)", "出典（EDGAR）"] in cols


def test_workstation_uses_sec_sic_for_sector(edgar_only_env):
    at = _start("app_bi_dashboard.py", data_mode="edgar_only")
    assert not at.exception
    assert edgar_only_env.sec_calls, "SEC の Submissions API を使っていない"
    url, ua = edgar_only_env.sec_calls[0]
    assert url.startswith("https://data.sec.gov/submissions/CIK") and "@" in ua
    assert len(edgar_only_env.sec_calls) <= 50  # 上位50社まで
    assert "運輸・通信・電気ガス" in list(at.multiselect[0].options)
    matrix = at.dataframe[0].value
    assert "1M リターン" not in matrix.columns and "sector" in matrix.columns


def test_compare_lists_8k_relative_to_form4():
    at = _start("app_compare_dashboard.py", data_mode="edgar_only")
    assert not at.exception
    tables = [df.value for df in at.dataframe]
    k8 = next(t for t in tables if "提出日からの日数" in t.columns)
    # 選んだ提出の前後30日（既定）の 8-K だけ。400日前のものは入らない
    assert len(k8) >= 1 and all(abs(int(d.rstrip("日"))) <= 30 for d in k8["提出日からの日数"])


def test_gate_on_defaults_to_edgar_only():
    """招待コードのゲートがある時は、data_mode を書かなくても edgar_only になる。"""
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.secrets["invite_codes"] = ["beta-code"]
    at.session_state["beta_invite_code"] = "beta-code"
    at.session_state["beta_consented"] = True
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = _texts(at)
    assert "Whale-Eye: Insider Intelligence" in text
    assert "Yahoo" not in text and "オプション" not in text


def test_workstation_says_when_sec_is_unreachable(monkeypatch):
    def down(url, ua):
        raise ConnectionError("SEC に届かない")

    monkeypatch.setattr(sec_company, "_get_json", down)
    at = _start("app_bi_dashboard.py", data_mode="edgar_only")
    assert not at.exception
    assert list(at.multiselect[0].options) == ["未分類"]
    assert any("業種（SIC）を取得できなかった" in str(c.value) for c in at.caption)
