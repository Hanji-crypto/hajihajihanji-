"""data_status（鮮度表示・古さの警告・免責）のテスト。実行: pytest"""
import sqlite3
from datetime import date

import pytest

import data_status as ds


@pytest.mark.parametrize(
    "latest, today, expected",
    [
        (date(2026, 11, 20), date(2026, 11, 20), 0),  # 当日
        (date(2026, 11, 20), date(2026, 11, 22), 0),  # 金→日（土日は数えない）
        (date(2026, 11, 20), date(2026, 11, 23), 1),  # 金→月
        (date(2026, 11, 20), date(2026, 11, 24), 2),  # 金→火
        (date(2026, 11, 20), date(2026, 11, 25), 3),  # 金→水 = 警告
        (date(2026, 11, 25), date(2026, 11, 30), 2),  # 感謝祭(11/26)を除く: 金・月
        (date(2026, 11, 25), date(2026, 11, 20), 0),  # 未来日
    ],
)
def test_business_days_since(latest, today, expected):
    assert ds.business_days_since(latest, today) == expected


def _db(tmp_path, filing_dates):
    path = tmp_path / "insider.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE insider_trades (filing_date TEXT)")
    conn.executemany("INSERT INTO insider_trades VALUES (?)", [(d,) for d in filing_dates])
    conn.commit()
    conn.close()
    return str(path)


def test_status_fresh(tmp_path):
    s = ds.get_data_status(_db(tmp_path, ["2026-11-18", "2026-11-20"]), today=date(2026, 11, 23))
    assert s.latest_filing == date(2026, 11, 20)
    assert s.stale_days == 1 and not s.is_stale
    assert s.updated_at is not None  # git が無い一時ディレクトリではファイルの更新時刻
    assert ds.stale_message(s) is None
    assert "2026-11-20" in ds.status_caption(s)


def test_status_stale_warns(tmp_path):
    s = ds.get_data_status(_db(tmp_path, ["2026-11-20"]), today=date(2026, 11, 25))
    assert s.stale_days == 3 and s.is_stale
    msg = ds.stale_message(s)
    assert "2026-11-20" in msg and "3 営業日" in msg


def test_status_empty_db_warns(tmp_path):
    s = ds.get_data_status(_db(tmp_path, []), today=date(2026, 11, 23))
    assert s.latest_filing is None and s.is_stale
    assert "読み取れません" in ds.stale_message(s)
    assert "不明" in ds.status_caption(s)


def test_status_missing_table(tmp_path):
    path = tmp_path / "x.db"
    sqlite3.connect(path).close()
    assert ds.latest_filing_date(str(path)) is None


def test_disclaimer_says_not_advice():
    assert "投資助言ではありません" in ds.DISCLAIMER


def test_source_caption_edgar_only_names_sec_only(tmp_path):
    s = ds.get_data_status(_db(tmp_path, ["2026-11-20"]), today=date(2026, 11, 23))
    full = ds.source_caption(s)
    assert "SEC EDGAR" in full and "Yahoo Finance" in full
    edgar = ds.source_caption(s, edgar_only=True)
    assert "SEC EDGAR" in edgar and "Yahoo" not in edgar and "yfinance" not in edgar
    assert "Yahoo" not in ds.SOURCE_NOTE_EDGAR_ONLY and "非公式" in ds.SOURCE_NOTE_EDGAR_ONLY
