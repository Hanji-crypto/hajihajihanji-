"""データの鮮度（最新提出日・最終更新時刻）と、全ページ共通の表示。

- 最新提出日 : insider_trades の MAX(filing_date)。
- 最終更新時刻: insider.db を最後に更新したコミットの時刻（自動更新ワークフローが毎回コミットする）。
               git が使えない環境ではファイルの更新時刻。
- 古さの判定 : 最新提出日の翌日から今日（米東部時間）までの EDGAR 営業日（土日・米連邦祝日を除く）の日数。
               STALE_BUSINESS_DAYS 以上なら警告する。
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

STALE_BUSINESS_DAYS = 3
US_EASTERN = ZoneInfo("America/New_York")
JST = ZoneInfo("Asia/Tokyo")
DISCLAIMER = (
    "本アプリは SEC 公開データ（Form 4 など）をもとにした一般的な情報提供のみを目的としており、"
    "個別の投資推奨・投資助言ではありません。"
    "データには誤りや遅れが含まれることがあります。投資判断はご自身の責任で行ってください。"
)

# 出典の表記。SEC・Yahoo の公認・提携に見えないよう「非公式」「関係はありません」を必ず添える（ロゴは使わない）。
SOURCE_NOTE = (
    "本アプリは個人が作った非公式のツールで、米国証券取引委員会（SEC）・Yahoo とは関係がなく、"
    "両者による承認・提携もありません。"
)

_EDGAR_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def business_days_since(latest: date, today: date) -> int:
    """latest の翌日〜today（当日を含む）の EDGAR 営業日数。latest が today 以降なら 0。"""
    start = pd.Timestamp(latest) + pd.Timedelta(days=1)
    end = pd.Timestamp(today)
    if start > end:
        return 0
    return len(pd.date_range(start, end, freq=_EDGAR_BDAY))


@dataclass
class DataStatus:
    latest_filing: date | None
    updated_at: datetime | None  # tz 付き
    stale_days: int
    is_stale: bool


def latest_filing_date(db_path: str) -> date | None:
    try:
        conn = sqlite3.connect(db_path)
        try:
            (v,) = conn.execute("SELECT MAX(filing_date) FROM insider_trades").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    ts = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(ts) else ts.date()


def last_updated_at(db_path: str) -> datetime | None:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", os.path.basename(db_path)],
            cwd=os.path.dirname(os.path.abspath(db_path)),
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if out:
            return datetime.fromisoformat(out)
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(db_path), tz=timezone.utc)
    except OSError:
        return None


def get_data_status(db_path: str, today: date | None = None) -> DataStatus:
    today = today or datetime.now(US_EASTERN).date()
    latest = latest_filing_date(db_path)
    stale = business_days_since(latest, today) if latest else STALE_BUSINESS_DAYS
    return DataStatus(latest, last_updated_at(db_path), stale, stale >= STALE_BUSINESS_DAYS)


def status_caption(s: DataStatus) -> str:
    latest = s.latest_filing.isoformat() if s.latest_filing else "不明"
    updated = s.updated_at.astimezone(JST).strftime("%Y-%m-%d %H:%M JST") if s.updated_at else "不明"
    return f"📅 データの最新提出日: **{latest}**　🔄 最終更新: **{updated}**"


def stale_message(s: DataStatus) -> str | None:
    if not s.is_stale:
        return None
    if s.latest_filing is None:
        return "⚠️ データの最新提出日を読み取れませんでした。データが更新されていない可能性があります。"
    return (
        f"⚠️ データが古くなっています: 最新提出日 {s.latest_filing.isoformat()} から "
        f"{s.stale_days} 営業日たっています（{STALE_BUSINESS_DAYS} 営業日以上で警告）。自動更新が止まっている可能性があります。"
    )


@st.cache_data(ttl=300, show_spinner=False)
def _cached_status(db_path: str, today: date) -> DataStatus:
    return get_data_status(db_path, today)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_quality(db_path: str):
    from data_quality import load_trades

    return load_trades(db_path)[1]


def render_page_header(db_path: str) -> None:
    """全ページ共通: 鮮度・古さの警告・品質チェック・免責を上部に小さく出す（streamlit_app.py から呼ぶ）。"""
    s = _cached_status(db_path, datetime.now(US_EASTERN).date())
    try:
        q = _cached_quality(db_path)
        quality = f"　🧹 品質チェック: {q.total_rows:,} 行中 {q.excluded_rows:,} 行を除外"
    except Exception:
        q, quality = None, ""
    st.caption(status_caption(s) + quality)
    msg = stale_message(s)
    if msg:
        st.warning(msg)
    if q is not None and q.excluded_rows:
        with st.expander("除外・補正の内訳（insider.db の誤データは表示時に除いています）", expanded=False):
            st.markdown("\n".join(f"- {line}" for line in q.summary_lines()))
    st.caption(f"ⓘ {DISCLAIMER}")


def source_caption(s: DataStatus, now: datetime | None = None) -> str:
    """出典と取得時点の1行。SEC は insider.db の最終更新時点、株価は画面の表示時点。"""
    now = now or datetime.now(timezone.utc)
    updated = s.updated_at.astimezone(JST).strftime("%Y-%m-%d %H:%M JST") if s.updated_at else "不明"
    shown = now.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")
    return (
        f"出典: U.S. SEC EDGAR（提出書類。Form 4 は {updated} 時点の取り込み、8-K は表示時に取得）"
        f"／株価: Yahoo Finance（yfinance 経由。{shown} 表示、最大1時間のキャッシュと提供元の遅延あり）"
    )


def render_page_footer(db_path: str) -> None:
    """全ページ共通のフッター: 出典・取得時点・免責（streamlit_app.py から各ページの後に呼ぶ）。"""
    s = _cached_status(db_path, datetime.now(US_EASTERN).date())
    st.divider()
    st.caption(source_caption(s))
    st.caption(f"ⓘ {DISCLAIMER} {SOURCE_NOTE}")
