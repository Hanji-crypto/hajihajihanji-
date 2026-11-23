"""SEC の Submissions API（data.sec.gov）から、企業の SIC コード・業種名を取る。

edgar_only モードで、yfinance の「セクター」の代わりに使う。
- 利用ルール（https://www.sec.gov/os/accessing-edgar-data）に合わせて、
  User-Agent に「名前 連絡先メール」を付け、毎秒10リクエストを超えないよう間隔を空ける。
  User-Agent は st.secrets の `sec_user_agent` で変えられる（無ければ edgartools と同じ識別子）。
- 取得結果は CIK ごとに st.cache_data で1週間キャッシュする（SIC はほとんど変わらない）。
- 取れなかった企業（通信エラー・未登録）は「未分類」にして、画面は他の情報だけで出す。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

import streamlit as st

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_USER_AGENT = "OptionScreener eae270@gmail.com"  # app_compare_dashboard.py の set_identity と同じ
MIN_INTERVAL_SEC = 0.15  # 毎秒10リクエスト未満
TIMEOUT_SEC = 10
UNCLASSIFIED = "未分類"

# SIC の大分類（Division）。米国の SIC マニュアルの区分を日本語にしたもの。
_SIC_DIVISIONS = [
    (100, 999, "農林水産業"),
    (1000, 1499, "鉱業"),
    (1500, 1799, "建設"),
    (2000, 3999, "製造業"),
    (4000, 4999, "運輸・通信・電気ガス"),
    (5000, 5199, "卸売"),
    (5200, 5999, "小売"),
    (6000, 6799, "金融・保険・不動産"),
    (7000, 8999, "サービス"),
    (9100, 9729, "行政"),
    (9900, 9999, "分類不能"),
]

_lock = threading.Lock()
_last_request = 0.0


def normalize_cik(cik) -> str | None:
    """'0001060391' / 1060391 / '1060391.0' → '0001060391'。数字でなければ None。"""
    if cik is None:
        return None
    s = str(cik).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if not s.isdigit() or int(s) == 0:
        return None
    return s.zfill(10)


def sic_division(sic) -> str:
    """SIC コード（'4953' など）→ 大分類の日本語名。分からなければ「未分類」。"""
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return UNCLASSIFIED
    for lo, hi, name in _SIC_DIVISIONS:
        if lo <= code <= hi:
            return name
    return UNCLASSIFIED


def user_agent() -> str:
    try:
        ua = st.secrets["sec_user_agent"] if "sec_user_agent" in st.secrets else None
    except Exception:
        ua = None
    return str(ua).strip() if ua and str(ua).strip() else DEFAULT_USER_AGENT


def _get_json(url: str, ua: str) -> dict:
    global _last_request
    with _lock:  # 間隔を空けて1件ずつ（SEC の毎秒10リクエストの上限を守る）
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
        return json.load(res)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def fetch_company_sic(cik: str, ua: str) -> dict | None:
    """CIK（10桁）→ {"sic": "4953", "sic_description": "Refuse Systems"}。取れなければ None（キャッシュしない）。"""
    data = _get_json(SUBMISSIONS_URL.format(cik=cik), ua)
    return {"sic": str(data.get("sic") or ""), "sic_description": str(data.get("sicDescription") or "")}


def company_sic_map(ciks) -> dict[str, dict]:
    """CIK の一覧 → {cik: {"sic", "sic_description", "division"}}。取れなかった CIK は入れない。"""
    ua = user_agent()
    out: dict[str, dict] = {}
    for raw in dict.fromkeys(ciks):
        cik = normalize_cik(raw)
        if cik is None:
            continue
        try:
            info = fetch_company_sic(cik, ua)  # 例外はキャッシュされないので、次の表示で取り直す
        except Exception:
            continue
        if info:
            out[str(raw)] = {**info, "division": sic_division(info["sic"])}
    return out
