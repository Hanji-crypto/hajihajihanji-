"""3ページを AppTest で起動するスモークテスト。実行: pytest test_smoke_pages.py

株価（yfinance）と SEC（edgartools）への通信は偽物に差し替え、CI でもネットワークに依存せず動かす。
各ページで「例外が出ない」「共通の鮮度表示と免責が出る」を確かめる。
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["app.py", "app_bi_dashboard.py", "app_compare_dashboard.py"]


def _ohlcv(n=260):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = 100 * 1.001 ** np.arange(n) * (1 + 0.02 * np.sin(np.arange(n) / 5))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1_000_000.0},
        index=idx,
    )


def _chain(spot=100.0):
    strikes = np.arange(80, 121, 5, dtype=float)
    base = pd.DataFrame({
        "contractSymbol": [f"X{k:.0f}" for k in strikes], "strike": strikes,
        "lastPrice": np.maximum(spot - strikes, 0) + 2.0, "bid": 1.0, "ask": 1.2,
        "volume": 100.0, "openInterest": 1000.0, "impliedVolatility": 0.35, "inTheMoney": strikes < spot,
    })
    return SimpleNamespace(calls=base.copy(), puts=base.copy())


class FakeTicker:
    def __init__(self, ticker):
        self.ticker = ticker
        self.options = ((pd.Timestamp.today() + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),)
        self.info = {"sector": "Technology"}

    def history(self, period="6mo", **_):
        return _ohlcv()

    def option_chain(self, expiry):
        return _chain(float(_ohlcv()["Close"].iloc[-1]))


def fake_download(tickers, *args, **kwargs):
    if isinstance(tickers, str):
        return _ohlcv()
    tickers = list(tickers)
    if len(tickers) == 1:
        return _ohlcv()
    return pd.concat({t: _ohlcv() for t in tickers}, axis=1)


def _no_network(*args, **kwargs):
    raise ConnectionError("テストでは SEC へ接続しない")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import edgar
    import yfinance

    monkeypatch.setattr(yfinance, "download", fake_download)
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    monkeypatch.setattr(edgar, "Company", _no_network)


def _texts(at):
    return " ".join(str(e.value) for e in list(at.caption) + list(at.markdown) + list(at.warning))


@pytest.mark.parametrize("page", PAGES)
def test_page_starts(page):
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.run()
    if page != "app.py":
        at.switch_page(page)
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert len(at.subheader) > 0  # ページ本体まで描画された（途中の st.stop で止まっていない）
    text = _texts(at)
    assert "データの最新提出日" in text and "最終更新" in text
    assert "投資助言ではありません" in text
    assert "出典: U.S. SEC EDGAR" in text and "Yahoo Finance" in text  # フッターの出典
    # 無効なティッカーは画面に出ない
    for sb in at.selectbox:
        assert "NONE" not in list(sb.options) and "N/A" not in list(sb.options)
