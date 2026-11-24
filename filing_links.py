"""Form 4 の原典リンク（表示用 HTML）を一度だけ解決し、filing_links.json に保存する。

なぜ:
    insider.db の filing_url（書類の索引ページ）は、EDGAR で開けないものが多い。同じ書類でも
    -index.htm / -index.html / 書類フォルダ / index.json が URL ごとに 200 か 404 かがばらばらで、
    決まった規則が無い（DB から無作為の60件で、今の URL 28%・発行体の -index.htm 62%・書類フォルダ 50%）。
    一方、書類の全文（{受付番号}.txt）は必ず取れ、そこに書かれた Form 4 の XML 名で作る
    表示用 HTML（.../xslF345X05/{XML名}）は 60/60 で開いた。

どうするか:
    - 解決: 発行体 CIK のフォルダの .txt を1回取り、Form 4 の XML 名を読み、表示用 HTML が開くかを1回確かめる
      （1書類あたり2リクエスト。開かなければ内部者 CIK のフォルダ・古い版の xsl も試す）。
    - 保存: filing_links.json（受付番号 → 表示用 HTML の URL）。insider.db は書き換えない。
      取り込み（a5_backfill_v3.py）が新しい書類を入れた時に同時に解決して追記し、auto_update.yml がコミットする。
      既存分は backfill_filing_links.yml（手動）が時間予算付きで埋める。途中で止まっても続きから再開できる。
    - 表示: 解決済みならその URL。未解決なら、必ず開く発行体の Form 4 一覧（browse-edgar）に落とす。

SEC の決まり: User-Agent に連絡先を入れる（環境変数 SEC_USER_AGENT か sec_company の既定値）。毎秒10件未満に抑える。

使い方（既存分を埋める）:
    python filing_links.py --max-minutes 170
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable

LINKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filing_links.json")
DB_PATH = "insider.db"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
XSL_VERSIONS = ("xslF345X05", "xslF345X04", "xslF345X03", "xslF345X02")
MIN_INTERVAL_SEC = 0.12   # 毎秒10件の上限より少なく（約8件/秒）
MAX_ATTEMPTS = 3          # 何度解決しても開かない書類は、それ以上試さない（Form 4 一覧に落とす）
SAVE_EVERY = 50

Getter = Callable[[str], tuple[int, bytes]]


# ---------------------------------------------------------------- URL
def browse_url(cik) -> str | None:
    """発行体の Form 4 一覧（EDGAR の会社ページ）。解決できなかった書類の落とし先。"""
    n = _cik_int(cik)
    if not n:
        return None
    return (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={n}"
            "&type=4&dateb=&owner=include&count=40")


def txt_url(cik, accession: str) -> str:
    return f"{ARCHIVES}/{_cik_int(cik)}/{accession.replace('-', '')}/{accession}.txt"


def xsl_url(cik, accession: str, xml_name: str, version: str = XSL_VERSIONS[0]) -> str:
    return f"{ARCHIVES}/{_cik_int(cik)}/{accession.replace('-', '')}/{version}/{xml_name}"


def _cik_int(cik) -> int | None:
    try:
        n = int(str(cik).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


_ARCHIVE_CIK = re.compile(r"/Archives/edgar/data/(\d+)/")


def folder_cik(url) -> int | None:
    """URL の /Archives/edgar/data/{CIK}/ の CIK（内部者 CIK を拾うのに使う）。"""
    m = _ARCHIVE_CIK.search(url) if isinstance(url, str) else None
    return int(m.group(1)) if m else None


def link_for(accession: str | None, cik, links: dict[str, str] | None, fallback: str | None = None) -> str | None:
    """表示に使う原典リンク: 解決済みの表示用 HTML → 発行体の Form 4 一覧 → 元の URL。"""
    if accession and links and links.get(accession):
        return links[accession]
    return browse_url(cik) or fallback


def is_resolved_link(url) -> bool:
    return isinstance(url, str) and "/xslF345X0" in url


# ---------------------------------------------------------------- .txt から Form 4 の XML 名
_DOC = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S | re.I)
_TYPE = re.compile(r"<TYPE>\s*([^\s<]+)", re.I)
_FILENAME = re.compile(r"<FILENAME>\s*([^\s<]+)", re.I)


def xml_name_from_txt(text: str) -> str | None:
    """書類の全文から、Form 4（3/5 も）本体の XML のファイル名。無ければ最初の .xml。"""
    first_xml = None
    for doc in _DOC.findall(text or ""):
        name = _FILENAME.search(doc)
        if not name or not name.group(1).lower().endswith(".xml"):
            continue
        first_xml = first_xml or name.group(1)
        t = _TYPE.search(doc)
        if t and t.group(1).upper().rstrip("/A") in {"3", "4", "5"}:
            return name.group(1)
    if first_xml:
        return first_xml
    m = _FILENAME.search(text or "")
    return m.group(1) if m and m.group(1).lower().endswith(".xml") else None


# ---------------------------------------------------------------- 取得（SEC の決まりを守る）
def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if ua:
        return ua
    from sec_company import DEFAULT_USER_AGENT
    return DEFAULT_USER_AGENT


class SecGetter:
    """User-Agent を付け、毎秒10件未満に抑えて GET する。(状態コード, 本文) を返す。通信失敗は 0。"""

    def __init__(self, user_agent: str | None = None, min_interval: float = MIN_INTERVAL_SEC, timeout: float = 20):
        self.user_agent = user_agent or sec_user_agent()
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.requests = 0

    def __call__(self, url: str) -> tuple[int, bytes]:
        for attempt in range(2):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt == 0:
                    time.sleep(2.0)   # 混雑・上限: 少し待って1回だけやり直す
                    continue
                return e.code, b""
            except Exception:
                if attempt == 0:
                    continue
                return 0, b""
        return 0, b""


def resolve(accession: str, issuer_cik, owner_cik=None, get: Getter | None = None) -> str | None:
    """1書類の表示用 HTML の URL を決める。開くものが無ければ None。"""
    get = get or SecGetter()
    ciks = [c for c in dict.fromkeys([_cik_int(issuer_cik), _cik_int(owner_cik)]) if c]
    text = None
    for c in ciks:
        status, body = get(txt_url(c, accession))
        if status == 200 and body:
            text = body.decode("latin-1", errors="replace")
            break
    if not text:
        return None
    xml = xml_name_from_txt(text)
    if not xml:
        return None
    for c in ciks:
        for v in XSL_VERSIONS:
            u = xsl_url(c, accession, xml, v)
            if get(u)[0] == 200:
                return u
    return None


# ---------------------------------------------------------------- 保存（filing_links.json）
def empty_store() -> dict:
    return {"links": {}, "unresolved": {}}


def load_store(path: str = LINKS_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    return {"links": dict(data.get("links") or {}), "unresolved": dict(data.get("unresolved") or {})}


def save_store(store: dict, path: str = LINKS_PATH) -> None:
    """途中で止まっても壊れないよう、別名に書いてから置き換える。差分が読みやすいよう1件1行・キー順。"""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"links": store["links"], "unresolved": store["unresolved"]}, fh,
                  ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


_cache: dict[str, tuple[float, dict[str, str]]] = {}


def load_links(path: str | None = None) -> dict[str, str]:
    """表示用: 受付番号 → URL。ファイルが変わった時だけ読み直す。"""
    path = path or LINKS_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    links = load_store(path)["links"]
    _cache[path] = (mtime, links)
    return links


# ---------------------------------------------------------------- まとめて解決（取り込み・手動の埋め直し）
def pending_filings(db_path: str, store: dict, since: str | None = None,
                    max_attempts: int = MAX_ATTEMPTS) -> list[tuple[str, int, int | None]]:
    """DB の書類のうち未解決のもの [(受付番号, 発行体CIK, 内部者CIK)]。新しい提出日から。DB は読むだけ。"""
    from data_quality import accession_from_url

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = "SELECT filing_url, cik, MAX(filing_date) AS d FROM insider_trades WHERE filing_url IS NOT NULL"
        params: list = []
        if since:
            q += " AND filing_date >= ?"
            params.append(since)
        q += " GROUP BY filing_url, cik ORDER BY d DESC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    out, seen = [], set()
    for url, cik, _ in rows:
        acc = accession_from_url(url)
        issuer = _cik_int(cik)
        if not acc or not issuer or acc in seen:
            continue
        seen.add(acc)
        if acc in store["links"] or int(store["unresolved"].get(acc, 0)) >= max_attempts:
            continue
        out.append((acc, issuer, folder_cik(url)))
    return out


def resolve_pending(db_path: str = DB_PATH, path: str = LINKS_PATH, *, since: str | None = None,
                    deadline: float | None = None, get: Getter | None = None, log=print,
                    max_attempts: int = MAX_ATTEMPTS, limit: int | None = None) -> dict:
    """未解決の書類を新しい順に解決し、filing_links.json に追記する。時間切れ・中断でも解決済みの分は保存する。

    deadline は time.time() の締め時刻。再実行すれば、解決済みは飛ばして続きから再開する。
    """
    store = load_store(path)
    todo = pending_filings(db_path, store, since=since, max_attempts=max_attempts)
    if limit is not None:
        todo = todo[:limit]
    get = get or SecGetter()
    result = {"pending": len(todo), "resolved": 0, "failed": 0, "stopped_by_budget": False, "interrupted": False}
    stop = {"flag": False}

    def _on_term(signum, frame):  # ステップのタイムアウト（SIGTERM）でも、それまでの分を保存してから終える
        stop["flag"] = True

    old = None
    try:
        old = signal.signal(signal.SIGTERM, _on_term)
    except ValueError:
        pass  # メインスレッド以外（Streamlit など）では登録できない
    done = 0
    try:
        for acc, issuer, owner in todo:
            if stop["flag"]:
                result["interrupted"] = True
                break
            if deadline and time.time() > deadline:
                result["stopped_by_budget"] = True
                break
            url = resolve(acc, issuer, owner, get=get)
            if url:
                store["links"][acc] = url
                store["unresolved"].pop(acc, None)
                result["resolved"] += 1
            else:
                store["unresolved"][acc] = int(store["unresolved"].get(acc, 0)) + 1
                result["failed"] += 1
            done += 1
            if done % SAVE_EVERY == 0:
                save_store(store, path)
                log(f"  🔗 原典リンク: {done}/{len(todo)} 件（解決 {result['resolved']} / 未解決 {result['failed']}）")
    finally:
        if done or not os.path.exists(path):
            save_store(store, path)
        if old is not None:
            signal.signal(signal.SIGTERM, old)
    result["remaining"] = len(todo) - done
    result["total_links"] = len(store["links"])
    return result


def _summary(result: dict, minutes: float) -> str:
    state = ("⚠️ 時間予算で途中終了（再実行で続きから再開）" if result["stopped_by_budget"]
             else "⚠️ 中断（再実行で続きから再開）" if result["interrupted"] else "✅ 完了")
    return "\n".join([
        "## 原典リンク（filing_links.json）", "",
        f"- 対象（未解決）: {result['pending']:,} 件 / 今回の解決: **{result['resolved']:,}** 件"
        f" / 開けなかった: {result['failed']:,} 件 / 残り: {result['remaining']:,} 件",
        f"- 解決済みの合計: {result['total_links']:,} 件 / 所要時間: {minutes:.1f} 分",
        f"- 状態: {state}",
    ])


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--out", default=LINKS_PATH)
    p.add_argument("--max-minutes", type=float, default=0, help="この時間(分)で打ち切って保存する（0=無制限）")
    p.add_argument("--since", default=None, help="この提出日 YYYY-MM-DD 以降の書類だけ")
    p.add_argument("--limit", type=int, default=None, help="最大件数（試し用）")
    args = p.parse_args(list(argv) if argv is not None else None)
    started = time.time()
    deadline = started + args.max_minutes * 60 if args.max_minutes > 0 else None
    result = resolve_pending(args.db, args.out, since=args.since, deadline=deadline, limit=args.limit)
    text = _summary(result, (time.time() - started) / 60)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
