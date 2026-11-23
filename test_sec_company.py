"""sec_company（SEC Submissions API の SIC 取得）のテスト。通信は偽物に差し替える。実行: pytest"""
import io
import json

import pytest
import streamlit as st

import sec_company as sc


@pytest.fixture(autouse=True)
def clear_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.mark.parametrize(
    "raw, expected",
    [("0001060391", "0001060391"), (1060391, "0001060391"), ("1060391.0", "0001060391"),
     (" 707605 ", "0000707605"), ("", None), (None, None), ("abc", None), ("0", None)],
)
def test_normalize_cik(raw, expected):
    assert sc.normalize_cik(raw) == expected


@pytest.mark.parametrize(
    "sic, expected",
    [("4953", "運輸・通信・電気ガス"), ("6022", "金融・保険・不動産"), ("3674", "製造業"), ("7372", "サービス"),
     ("2834", "製造業"), ("1311", "鉱業"), ("5812", "小売"), ("", sc.UNCLASSIFIED), (None, sc.UNCLASSIFIED),
     ("0000", sc.UNCLASSIFIED)],
)
def test_sic_division(sic, expected):
    assert sc.sic_division(sic) == expected


def test_user_agent_default_and_secret():
    assert sc.user_agent() == sc.DEFAULT_USER_AGENT
    assert "@" in sc.DEFAULT_USER_AGENT  # SEC は名前と連絡先メールを求める
    st.secrets._secrets = {"sec_user_agent": "Whale-Eye admin@example.com"}
    assert sc.user_agent() == "Whale-Eye admin@example.com"


def test_request_sends_user_agent(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        return io.BytesIO(json.dumps({"sic": "4953", "sicDescription": "Refuse Systems"}).encode())

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    got = sc.company_sic_map(["0001060391"])
    assert seen["url"] == "https://data.sec.gov/submissions/CIK0001060391.json"
    assert seen["ua"] == sc.DEFAULT_USER_AGENT and seen["timeout"] == sc.TIMEOUT_SEC
    assert got == {"0001060391": {"sic": "4953", "sic_description": "Refuse Systems", "division": "運輸・通信・電気ガス"}}


def test_results_are_cached_and_failures_skipped(monkeypatch):
    calls = []

    def fake_get_json(url, ua):
        calls.append(url)
        if "0000000002" in url:
            raise ConnectionError("SEC に届かない")
        return {"sic": "6022", "sicDescription": "State Commercial Banks"}

    monkeypatch.setattr(sc, "_get_json", fake_get_json)
    first = sc.company_sic_map(["1", "2", "1", "x"])
    assert set(first) == {"1"} and first["1"]["division"] == "金融・保険・不動産"
    assert len(calls) == 2  # 重複・不正な CIK は問い合わせない
    sc.company_sic_map(["1"])
    assert len(calls) == 2  # 2回目はキャッシュから（SEC に再度問い合わせない）
    sc.company_sic_map(["2"])
    assert len(calls) == 3  # 失敗はキャッシュしない（次の表示で取り直す）


def test_requests_are_spaced(monkeypatch):
    """毎秒10リクエストの上限を守るため、連続した問い合わせの間を MIN_INTERVAL_SEC 以上空ける。"""
    times = []

    def fake_urlopen(req, timeout):
        times.append(sc.time.monotonic())
        return io.BytesIO(b'{"sic": "1311", "sicDescription": "Crude Petroleum"}')

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    sc.company_sic_map(["11", "12", "13"])
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(gaps) == 2 and all(g >= sc.MIN_INTERVAL_SEC * 0.95 for g in gaps)
