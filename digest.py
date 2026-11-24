"""毎朝の日本語メール「昨夜のインサイダー大口買い Top5」を作って配信する。

実行: python digest.py [--date YYYY-MM-DD] [--out digest_out] [--dry-run] [--no-8k]

■ 何を選ぶか
- 対象日: Actions では送る直前（日本時間 6:30 ごろ = 米国東部の夕方）に、作業コピーの insider.db へ
  EDGAR の最新提出フィードから当日分を取り込み（取り込みスクリプトの --current。コミットはしない）、
  米国東部の当日の提出分を「米国東部 X時 までの提出分」と締め時刻つきで載せる。
  取り込みが失敗したら、取り込み前の insider.db の直近の提出日で作り、本文に遅れを書く。
  --ingest-status を渡さない時は米国東部の前営業日（EDGAR の営業日 = 土日・米連邦祝日を除く）。--date で上書きできる。
- insider.db の insider_trades から対象日に提出された行を読み、data_quality.clean_trades の基準で
  除外・補正したうえで、Form 4 の取引コード P（市場での買い）だけを使う。
  取り込み側（a5_backfill_v3.py）は edgartools の common_stock_purchases（= コード P）だけを保存するので、
  今の DB の行はすべて P。将来 transaction_code 列が入った時は、その列で P 以外を除く。
- 1社（ティッカー）あたりの合計金額の大きい順に Top5。合計金額が同じなら、ティッカーのアルファベット順。
- 各社に、直近30日（対象日を含む）の同じ銘柄の買いの書類数・内部者の人数と、
  対象日に同じ会社が出した 8-K の項目（SEC Submissions API）を添える。

■ 書かないこと
- 株価・騰落率（SEC EDGAR のデータだけを使う。yfinance は読み込まない）。
- 個別の投資推奨に見える言葉（BANNED_TERMS）。事実（誰が・何株・いくらで・いつ・どの書類）と原典リンクだけ。

■ 配信
- send_digest() の1か所に閉じ込める。BUTTONDOWN_API_KEY があれば Buttondown の API で送り、無ければ dry-run。
- dry-run は送らずに HTML・テキストを --out に書き出す（Actions ではアーティファクトと実行サマリに残す）。
- 対象日のデータが無い日（休場日・取り込み失敗）は送らない。

■ 設定（環境変数。値はコードやリポジトリに書かない。Actions では secrets / variables から渡す）
- DIGEST_SENDER_NAME      : 送信者の表示名（例: 個人名や屋号）
- DIGEST_SENDER_CONTACT   : 送信者の連絡先（メールアドレスや問い合わせ先 URL）
- DIGEST_DASHBOARD_URL    : ダッシュボードの URL。{ticker} を含めれば銘柄ごとに差し込む
- DIGEST_UNSUBSCRIBE_URL  : 配信停止のページ（Buttondown で送る時は、無ければ Buttondown の停止リンクを使う）
- BUTTONDOWN_API_KEY      : これがある時だけ実際に送る
- SEC_USER_AGENT          : SEC へのアクセスに付ける「名前 連絡先」（無ければ sec_company と同じ識別子）
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import pandas as pd

from data_quality import accession_from_url, clean_trades
from data_status import JST, US_EASTERN, _EDGAR_BDAY, last_updated_at

TOP_N = 5
CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3  # 30日で3人以上の内部者が買っていれば「複数の内部者による買い」と書く
PURCHASE_CODE = "P"

# 個別の投資推奨・値動きの予想に見える言葉。文面に入っていないことをテストと送信前の検査で確かめる。
# 「大口買い」「市場での買い」は取引の種類（事実）なので対象にしない。
BANNED_TERMS = (
    "推奨", "おすすめ", "オススメ", "狙い目", "買い時", "買い場", "買いシグナル", "買うべき", "今が買",
    "上がる", "上昇", "値上がり", "急騰", "高騰", "爆上げ", "儲", "チャンス", "注目銘柄", "期待",
    "有望", "割安", "売り時", "下がる", "目標株価", "必ず",
)

DISCLAIMER = (
    "本メールは SEC の公開データ（Form 4・8-K）をもとにした一般的な情報提供のみを目的としており、"
    "投資助言ではなく、特定の銘柄の売買を勧めるものでもありません。データには誤りや遅れが含まれることがあります。"
    "投資判断はご自身の責任で行ってください。"
)
NOT_AFFILIATED = (
    "本メールは個人による非公式の集計で、米国証券取引委員会（SEC）とは関係がなく、"
    "SEC による承認・提携もありません。"
)
BUTTONDOWN_UNSUBSCRIBE = "{{ unsubscribe_url }}"  # Buttondown が宛先ごとの停止リンクに置き換える

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
BUTTONDOWN_EMAILS_URL = "https://api.buttondown.com/v1/emails"

# 8-K の項目番号 → 日本語の件名（SEC Form 8-K の項目名を訳したもの）
ITEM_LABELS = {
    "1.01": "重要な契約の締結", "1.02": "重要な契約の終了", "1.03": "破産・管財",
    "1.05": "重要なサイバーセキュリティ事案",
    "2.01": "資産の取得・処分の完了", "2.02": "業績・財務状況（決算）", "2.03": "直接の金融債務の発生",
    "2.04": "債務の期限前弁済などの発生", "2.05": "撤退・事業縮小の費用", "2.06": "重要な減損",
    "3.01": "上場廃止・上場基準の不適合", "3.02": "未登録の株式の発行", "3.03": "株主の権利の重要な変更",
    "4.01": "監査人の変更", "4.02": "過去の財務諸表に依拠できない旨",
    "5.01": "支配権の変更", "5.02": "役員・取締役の異動・報酬", "5.03": "定款・会計年度の変更",
    "5.05": "倫理規程の変更", "5.07": "株主総会の議決結果", "5.08": "株主による取締役候補の推薦",
    "7.01": "Regulation FD による開示", "8.01": "その他の重要事象", "9.01": "財務諸表・添付資料",
}


# ---------------------------------------------------------------- データ
@dataclass
class Insider:
    name: str
    position: str


@dataclass
class CompanyPick:
    rank: int
    ticker: str
    company: str
    cik: str | None
    insiders: list[Insider]
    shares: float
    avg_price: float
    total_value: float
    filing_date: str
    trade_dates: tuple[str, str]  # (最初の取引日, 最後の取引日)
    filing_urls: list[str]
    recent_filings_30d: int = 0
    recent_insiders_30d: int = 0
    eight_k: list[dict] = field(default_factory=list)  # [{"items": [...], "url": ...}]

    @property
    def is_cluster(self) -> bool:
        return self.recent_insiders_30d >= CLUSTER_MIN_INSIDERS


def previous_business_day(now: datetime | None = None) -> date:
    """米国東部時間で「今日」の前の EDGAR 営業日。"""
    now = now or datetime.now(US_EASTERN)
    today = pd.Timestamp(now.astimezone(US_EASTERN).date())
    return (today - _EDGAR_BDAY).date()


def load_raw(db_path: str, since: date, until: date) -> pd.DataFrame:
    """対象日を含む直近30日分（集団買いの判定用）の生データを読む。DB は書き換えない。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(
            "SELECT * FROM insider_trades WHERE filing_date BETWEEN ? AND ?",
            conn, params=(since.isoformat(), until.isoformat()),
        )
    finally:
        conn.close()


def purchases_only(df: pd.DataFrame) -> pd.DataFrame:
    """取引コード P（市場での買い）だけ。transaction_code 列が無い DB は全行が P（取り込み側の仕様）。"""
    if "transaction_code" not in df.columns:
        return df
    return df[df["transaction_code"].astype(str).str.strip().str.upper() == PURCHASE_CODE]


def _accession(url) -> str:
    return accession_from_url(url) or str(url)


def issuer_filing_url(url: str, cik) -> str:
    """書類の索引ページを、発行会社の CIK のフォルダで組み直す。

    insider.db の filing_url は、取り込み時の書類の提出者（内部者本人など）の CIK のフォルダを指すことがあり、
    EDGAR ではそのフォルダに置かれず 404 になる書類がある。発行会社のフォルダには必ず置かれるため、そちらに直す。
    CIK か受付番号が読めない時は元の URL のまま。
    """
    acc = accession_from_url(url)
    try:
        cik_num = int(str(cik).strip())
    except (TypeError, ValueError):
        return url
    if not acc or cik_num <= 0:
        return url
    return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc.replace('-', '')}/{acc}-index.html"


def select_top(raw: pd.DataFrame, target: date, n: int = TOP_N) -> list[CompanyPick]:
    """品質判定 → P だけ → 対象日の提出分を1社ごとに合計 → 金額の大きい順に n 社。"""
    clean, _ = clean_trades(raw)
    clean = purchases_only(clean)
    if clean.empty:
        return []
    clean = clean.assign(filing_date=clean["filing_date"].astype(str).str[:10])
    day = clean[clean["filing_date"] == target.isoformat()]
    if day.empty:
        return []

    totals = (
        day.groupby("ticker")["total_value"].sum().reset_index()
        .sort_values(["total_value", "ticker"], ascending=[False, True], kind="mergesort")
        .head(n)
    )
    window_start = (pd.Timestamp(target) - pd.Timedelta(days=CLUSTER_WINDOW_DAYS - 1)).date().isoformat()
    recent = clean[(clean["filing_date"] >= window_start) & (clean["filing_date"] <= target.isoformat())]

    picks = []
    for rank, tk in enumerate(totals["ticker"], 1):
        g = day[day["ticker"] == tk].sort_values("id") if "id" in day.columns else day[day["ticker"] == tk]
        insiders = []
        for name, pos in g[["insider", "position"]].fillna("").itertuples(index=False):
            name = str(name).strip() or "（氏名の記載なし）"
            if name not in {i.name for i in insiders}:
                insiders.append(Insider(name=name, position=str(pos).strip()))
        shares = float(g["total_shares"].sum())
        value = float(g["total_value"].sum())
        trade_dates = sorted(str(d)[:10] for d in g["buy_date"].dropna()) or [target.isoformat()]
        r = recent[recent["ticker"] == tk]
        cik = str(g["cik"].dropna().iat[0]) if "cik" in g.columns and g["cik"].notna().any() else None
        picks.append(CompanyPick(
            rank=rank,
            ticker=tk,
            company=str(g["company"].mode().iat[0]) if g["company"].notna().any() else tk,
            cik=cik,
            insiders=insiders,
            shares=shares,
            avg_price=value / shares if shares else 0.0,
            total_value=value,
            filing_date=target.isoformat(),
            trade_dates=(trade_dates[0], trade_dates[-1]),
            filing_urls=list(dict.fromkeys(issuer_filing_url(u, cik) for u in g["filing_url"].dropna().astype(str))),
            recent_filings_30d=int(r["filing_url"].map(_accession).nunique()),
            recent_insiders_30d=int(r["insider"].fillna("").str.strip().str.upper().nunique()),
        ))
    return picks


# ---------------------------------------------------------------- 8-K（SEC Submissions API）
def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if ua:
        return ua
    from sec_company import DEFAULT_USER_AGENT  # 取り込み側・ダッシュボードと同じ識別子

    return DEFAULT_USER_AGENT


def _fetch_submissions(cik: str) -> dict:
    req = urllib.request.Request(
        SUBMISSIONS_URL.format(cik=cik),
        headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def eight_k_on(submissions: dict, cik: str, target: date) -> list[dict]:
    """Submissions API の結果から、対象日に出た 8-K（8-K/A を含む）を [{"form","items","url"}] で返す。"""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    out = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A") or (recent.get("filingDate") or [""])[i] != target.isoformat():
            continue
        acc = recent["accessionNumber"][i]
        doc = (recent.get("primaryDocument") or [""] * len(forms))[i]
        items = [s.strip() for s in str((recent.get("items") or [""] * len(forms))[i]).split(",") if s.strip()]
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
        out.append({"form": form, "items": items, "url": f"{base}/{doc}" if doc else f"{base}/"})
    return out


def attach_8k(picks: list[CompanyPick], target: date,
              fetch: Callable[[str], dict] = _fetch_submissions) -> list[str]:
    """各社に対象日の 8-K を付ける。取れなかった会社のティッカーを返す（文面には「確認できず」と書かない）。"""
    from sec_company import normalize_cik

    failed = []
    for p in picks:
        cik = normalize_cik(p.cik)
        if cik is None:
            failed.append(p.ticker)
            continue
        try:
            p.eight_k = eight_k_on(fetch(cik), cik, target)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
            failed.append(p.ticker)
        time.sleep(0.15)  # SEC の毎秒10リクエストの上限を守る
    return failed


# ---------------------------------------------------------------- 鮮度（どの提出日を、いつ時点まで載せるか）
@dataclass
class Freshness:
    """kind: fresh（送る直前に当日分まで取り込めた）/ partial（時間切れで一部）/ fallback（取り込み失敗）/ manual。"""
    kind: str
    target: date | None  # None = 送らない（米国東部の休場日）
    fetched_at: datetime | None  # 出典の「取得時点」
    cutoff: datetime | None = None  # この時刻までに EDGAR が受け付けた提出分（fresh / partial）

    def note(self) -> str:
        if self.kind in ("fresh", "partial") and self.cutoff:
            c = self.cutoff.astimezone(US_EASTERN)
            s = (f"米国東部 {c.month}/{c.day} {c:%H:%M} までの提出分です"
                 f"（日本時間 {self.cutoff.astimezone(JST):%H:%M} に EDGAR から取得。同じ日のそれより後の提出は含みません）。")
            if self.kind == "partial":
                s += "取り込みが時間内に終わらず、この時刻までの提出のうち一部が含まれていない可能性があります。"
            return s
        if self.kind == "fallback":
            when = self.fetched_at.astimezone(JST).strftime("%m/%d %H:%M") if self.fetched_at else "不明"
            return (f"【遅れ】今朝の取り込みに失敗したため、前回の取り込み（日本時間 {when}）時点のデータで作成しています。"
                    "最新の提出分は含まれていません。")
        return ""


def read_ingest_status(path: str | None) -> dict | None:
    """取り込みスクリプトの --status-file の結果。無い・読めない・エラーありなら None（＝取り込み失敗）。"""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            status = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict) or status.get("error") or not status.get("feed_fetched_at"):
        return None
    return status


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def is_business_day(d: date) -> bool:
    return bool(_EDGAR_BDAY.is_on_offset(pd.Timestamp(d)))


def latest_filing_on_or_before(db_path: str, day: date) -> date | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        (v,) = conn.execute("SELECT MAX(filing_date) FROM insider_trades WHERE filing_date <= ?",
                            (day.isoformat(),)).fetchone()
    finally:
        conn.close()
    return date.fromisoformat(str(v)[:10]) if v else None


def resolve_freshness(status: dict | None, ingest_attempted: bool, fallback_db: str,
                      committed_at: datetime | None, now: datetime | None = None) -> Freshness:
    """送る直前の取り込みの結果から、載せる提出日と本文の注記を決める。"""
    now = now or datetime.now(US_EASTERN)
    if status is not None:
        cutoff = _parse_utc(status["feed_fetched_at"])
        day = cutoff.astimezone(US_EASTERN).date()
        kind = "partial" if status.get("stopped_by_budget") else "fresh"
        return Freshness(kind, day if is_business_day(day) else None, cutoff, cutoff)
    if ingest_attempted:  # 失敗: 取り込み前の insider.db の直近の提出日で作る
        today = now.astimezone(US_EASTERN).date()
        return Freshness("fallback", latest_filing_on_or_before(fallback_db, today), committed_at)
    return Freshness("manual", previous_business_day(now), committed_at)


# ---------------------------------------------------------------- 文面
@dataclass
class DigestConfig:
    sender_name: str = ""
    sender_contact: str = ""
    dashboard_url: str = ""
    unsubscribe_url: str = ""

    @classmethod
    def from_env(cls, env=os.environ) -> "DigestConfig":
        return cls(
            sender_name=env.get("DIGEST_SENDER_NAME", "").strip(),
            sender_contact=env.get("DIGEST_SENDER_CONTACT", "").strip(),
            dashboard_url=env.get("DIGEST_DASHBOARD_URL", "").strip(),
            unsubscribe_url=env.get("DIGEST_UNSUBSCRIBE_URL", "").strip(),
        )

    def dashboard_link(self, ticker: str) -> str:
        if not self.dashboard_url:
            return ""
        if "{ticker}" in self.dashboard_url:
            return self.dashboard_url.replace("{ticker}", urllib.request.quote(ticker))
        return self.dashboard_url


@dataclass
class Digest:
    subject: str
    text: str
    html: str


def _usd(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def _price(v: float) -> str:
    return f"${v:,.2f}"


def _md(d: str) -> str:
    return f"{int(d[5:7])}/{int(d[8:10])}"


def _insider_line(p: CompanyPick) -> str:
    names = [f"{i.name}（{i.position}）" if i.position else i.name for i in p.insiders]
    return f"{len(p.insiders)}人: " + "、".join(names)


def _trade_dates(p: CompanyPick) -> str:
    a, b = p.trade_dates
    return a if a == b else f"{a} 〜 {b}"


def _recent_line(p: CompanyPick) -> str:
    s = f"直近30日の買いの書類 {p.recent_filings_30d} 件・内部者 {p.recent_insiders_30d} 人"
    if p.is_cluster:
        s += f"（{CLUSTER_MIN_INSIDERS}人以上の内部者による買い）"
    return s


def _eight_k_line(e: dict) -> str:
    labels = [f"Item {it} {ITEM_LABELS[it]}" if it in ITEM_LABELS else f"Item {it}" for it in e["items"]]
    return f"{e['form']}: " + ("、".join(labels) if labels else "項目の記載なし")


def _filing_label(url: str) -> str:
    acc = accession_from_url(url)
    return f"Form 4（受付番号 {acc}）" if acc else "Form 4"


def build_digest(picks: list[CompanyPick], target: date, fetched_at: datetime | None,
                 config: DigestConfig, unsubscribe: str, freshness_note: str = "") -> Digest:
    """件名・プレーンテキスト・HTML を作る。picks は空でない前提（空の日は送らない）。"""
    subject = f"昨夜のインサイダー大口買い Top5（{_md(target.isoformat())} 提出分）"
    total = sum(p.total_value for p in picks)
    summary = (
        f"{target.isoformat()}（米国東部）に SEC EDGAR へ提出された Form 4 の市場での買い（取引コード P）のうち、"
        f"1社あたりの合計金額の上位 {len(picks)} 社です（{len(picks)} 社の合計 {_usd(total)}）。"
    )
    fetched = fetched_at.astimezone(JST).strftime("%Y-%m-%d %H:%M JST") if fetched_at else "不明"
    source = f"出典: U.S. SEC EDGAR（Form 4・8-K の公開データ。取得時点: {fetched}）"
    sender = "送信者: " + (config.sender_name or "（未設定）") + " / 連絡先: " + (config.sender_contact or "（未設定）")
    unsub_text = f"配信停止: 次のリンクから停止できます {unsubscribe}" if unsubscribe else \
        "配信停止: このメールに「配信停止」と返信してください。"

    # --- プレーンテキスト
    t = [subject, "", summary] + ([freshness_note] if freshness_note else []) + [""]
    for p in picks:
        t += [
            f"{p.rank}. {p.company}（{p.ticker}）",
            f"   合計金額: {_usd(p.total_value)} / 株数: {p.shares:,.0f} 株 / 平均単価: {_price(p.avg_price)}",
            f"   内部者: {_insider_line(p)}",
            f"   取引日: {_trade_dates(p)} / 提出日: {p.filing_date}",
            f"   {_recent_line(p)}",
        ]
        t += [f"   同じ日の {_eight_k_line(e)}  {e['url']}" for e in p.eight_k]
        t += [f"   原典: {_filing_label(u)} {u}" for u in p.filing_urls]
        if config.dashboard_link(p.ticker):
            t.append(f"   ダッシュボード: {config.dashboard_link(p.ticker)}")
        t.append("")
    t += ["—", DISCLAIMER, NOT_AFFILIATED, source, unsub_text, sender]
    text = "\n".join(t) + "\n"

    # --- HTML（値はすべてエスケープ。スクリプト・外部の読み込みは入れない）
    e = html.escape

    def a(url: str, label: str) -> str:
        return f'<a href="{e(url, quote=True)}" style="color:#2563EB;">{e(label)}</a>'

    cards = []
    for p in picks:
        rows = [
            ("合計金額", e(_usd(p.total_value))),
            ("株数・平均単価", e(f"{p.shares:,.0f} 株 / {_price(p.avg_price)}")),
            ("内部者", e(_insider_line(p))),
            ("取引日・提出日", e(f"{_trade_dates(p)} / {p.filing_date}")),
            ("直近30日", e(_recent_line(p))),
        ]
        for k in p.eight_k:
            rows.append(("同じ日の 8-K", a(k["url"], _eight_k_line(k))))
        rows.append(("原典（EDGAR）", "<br>".join(a(u, _filing_label(u)) for u in p.filing_urls)))
        if config.dashboard_link(p.ticker):
            rows.append(("ダッシュボード", a(config.dashboard_link(p.ticker), f"{p.ticker} を開く")))
        body_rows = "".join(
            f'<tr><td style="padding:4px 8px 4px 0;color:#6B7280;white-space:nowrap;vertical-align:top;">{e(k)}</td>'
            f'<td style="padding:4px 0;vertical-align:top;">{v}</td></tr>' for k, v in rows
        )
        cards.append(
            '<div style="border:1px solid #E5E7EB;border-radius:8px;padding:12px 16px;margin:0 0 12px;">'
            f'<div style="font-size:16px;font-weight:bold;margin:0 0 6px;">{p.rank}. {e(p.company)}'
            f'（{e(p.ticker)}）</div>'
            f'<table style="border-collapse:collapse;font-size:14px;">{body_rows}</table></div>'
        )
    unsub_html = (f"配信停止: {a(unsubscribe, '配信を停止する')}" if unsubscribe
                  else e("配信停止: このメールに「配信停止」と返信してください。"))
    footer = "".join(f'<p style="margin:4px 0;">{x}</p>' for x in (
        e(DISCLAIMER), e(NOT_AFFILIATED), e(source), unsub_html, e(sender)))
    html_body = (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        f"<title>{e(subject)}</title></head>"
        '<body style="margin:0;padding:16px;background:#FFFFFF;color:#111827;'
        "font-family:-apple-system,'Hiragino Sans','Noto Sans JP',sans-serif;line-height:1.6;\">"
        '<div style="max-width:640px;margin:0 auto;">'
        f'<h1 style="font-size:20px;margin:0 0 8px;">{e(subject)}</h1>'
        f'<p style="margin:0 0 16px;">{e(summary)}</p>'
        + (f'<p style="margin:0 0 16px;padding:8px 12px;border-radius:6px;font-size:13px;'
           f'background:{"#FEF3C7" if freshness_note.startswith("【遅れ】") else "#F3F4F6"};">{e(freshness_note)}</p>'
           if freshness_note else "")
        + "".join(cards)
        + f'<div style="border-top:1px solid #E5E7EB;margin-top:16px;padding-top:8px;font-size:12px;color:#6B7280;">{footer}</div>'
        "</div></body></html>"
    )
    return Digest(subject=subject, text=text, html=html_body)


def banned_terms_in(*texts: str) -> list[str]:
    return [w for w in BANNED_TERMS if any(w in t for t in texts)]


# ---------------------------------------------------------------- 配信（送り先を差し替えるのはここだけ）
@dataclass
class SendResult:
    mode: str  # "buttondown" / "dry-run"
    detail: str


def send_digest(digest: Digest, out_dir: str, env=os.environ, dry_run: bool = False,
                post: Callable[[str, dict, dict], dict] | None = None) -> SendResult:
    """文面を配信する。常に out_dir に HTML・テキストを書き出し、キーがある時だけ Buttondown で送る。"""
    os.makedirs(out_dir, exist_ok=True)
    for name, body in (("digest.html", digest.html), ("digest.txt", digest.text), ("subject.txt", digest.subject + "\n")):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    key = env.get("BUTTONDOWN_API_KEY", "").strip()
    if dry_run or not key:
        why = "--dry-run 指定" if dry_run else "BUTTONDOWN_API_KEY が未設定"
        return SendResult("dry-run", f"送信せず、{out_dir} に書き出しました（{why}）")

    payload = {
        "subject": digest.subject,
        # Buttondown は本文の HTML/Markdown を自動判定する。HTML として扱うよう先頭で明示する。
        "body": "<!-- buttondown-editor-mode: fancy -->\n" + digest.html,
        "status": "about_to_send",
    }
    headers = {"Authorization": f"Token {key}", "Content-Type": "application/json"}
    res = (post or _post_json)(BUTTONDOWN_EMAILS_URL, payload, headers)
    return SendResult("buttondown", f"Buttondown に送信を依頼しました（id: {res.get('id', '?')}）")


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as err:  # 本文は出すが、ヘッダ（API キー）は出さない
        raise RuntimeError(f"Buttondown API エラー {err.code}: {err.read()[:500]!r}") from None


# ---------------------------------------------------------------- 実行
def _write_summary(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


def _set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="insider.db")
    ap.add_argument("--date", help="対象の提出日（YYYY-MM-DD）。省略時は米国東部の前営業日")
    ap.add_argument("--out", default="digest_out")
    ap.add_argument("--dry-run", action="store_true", help="キーがあっても送らない")
    ap.add_argument("--no-8k", action="store_true", help="8-K を SEC に問い合わせない")
    ap.add_argument("--ingest-status",
                    help="送る直前の取り込み（--current --status-file）の結果。成功なら米国東部の当日分を締め時刻つきで、"
                         "失敗（無い・エラー）なら --fallback-db の直近の提出日で作り、本文に遅れを書く")
    ap.add_argument("--fallback-db", help="取り込み前の insider.db の写し（取り込み失敗時に使う。既定は --db）")
    args = ap.parse_args(argv)

    committed_at = last_updated_at(args.db)  # insider.db を最後にコミットした時刻（作業コピーへの取り込みは含まない）
    if args.date:
        fresh = Freshness("manual", date.fromisoformat(args.date), committed_at)
    else:
        fresh = resolve_freshness(read_ingest_status(args.ingest_status), bool(args.ingest_status),
                                  args.fallback_db or args.db, committed_at)
    db = args.fallback_db if fresh.kind == "fallback" and args.fallback_db else args.db
    _set_output("freshness", fresh.kind)
    if fresh.target is None:
        _set_output("status", "skipped")
        _write_summary(["## インサイダー大口買い Top5", "",
                        f"- 米国東部の休場日（またはデータなし）のため送りません（取り込み: {fresh.kind}）。"])
        return 0
    target = fresh.target
    since = (pd.Timestamp(target) - pd.Timedelta(days=CLUSTER_WINDOW_DAYS - 1)).date()
    picks = select_top(load_raw(db, since, target), target)
    _set_output("target_date", target.isoformat())
    if not picks:
        _set_output("status", "skipped")
        _write_summary(["## インサイダー大口買い Top5", "",
                        f"- 対象日 {target.isoformat()} の市場での買いがありません。送りません（休場日・取り込み前など。取り込み: {fresh.kind}）。"])
        return 0

    failed_8k = [] if args.no_8k else attach_8k(picks, target)
    config = DigestConfig.from_env()
    via_buttondown = bool(os.environ.get("BUTTONDOWN_API_KEY", "").strip()) and not args.dry_run
    unsubscribe = config.unsubscribe_url or (BUTTONDOWN_UNSUBSCRIBE if via_buttondown else "")
    digest = build_digest(picks, target, fresh.fetched_at, config, unsubscribe, fresh.note())

    banned = banned_terms_in(digest.subject, digest.text, digest.html)
    if banned:  # 社名などに偶然入った時も、人が確かめるまで送らない
        _set_output("status", "blocked")
        send_digest(digest, args.out, dry_run=True)
        _write_summary(["## インサイダー大口買い Top5", "", f"- ⚠️ 禁止語 {banned} が入ったため送りません。{args.out} を確認してください。"])
        return 1

    result = send_digest(digest, args.out, dry_run=args.dry_run)
    _set_output("status", "sent" if result.mode == "buttondown" else "dry-run")
    missing = [k for k, v in (("DIGEST_SENDER_NAME", config.sender_name), ("DIGEST_SENDER_CONTACT", config.sender_contact),
                              ("DIGEST_DASHBOARD_URL", config.dashboard_url)) if not v]
    lines = ["## インサイダー大口買い Top5", "",
             f"- 対象日: **{target.isoformat()}** / 件名: {digest.subject}",
             f"- 鮮度: **{fresh.kind}** {fresh.note()}",
             f"- 配信: **{result.mode}** — {result.detail}"]
    if missing:
        lines.append(f"- 未設定: {', '.join(missing)}（文面には「未設定」と出ます）")
    if failed_8k:
        lines.append(f"- 8-K を確認できなかった銘柄: {', '.join(failed_8k)}")
    lines += ["", "```text", digest.text.rstrip(), "```"]
    _write_summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
