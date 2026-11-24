#!/usr/bin/env python3
"""Taiwan Affairs Office (TAO) press-conference transcript collector and rebuilder.

Single-file CLI, standard library only.

Source   https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/
Listing  50 items per page, index.htm / index_1.htm ... index_N.htm (GBK)
Article  new template: div.TRS_Editor (paragraphs in <p>); old template:
         div#contentArea (div/br/font blocks)

Outputs
  data/YYYY-MM-DD.md          cleaned transcript (front matter + body)
  data/jsonl/YYYY-MM-DD.jsonl structured records: one conference line + one line per Q&A
  gtb_qa.jsonl                all Q&A pairs merged (type=qa only)
  gtb.db                      SQLite: conference / qa / qa_fts (trigram Chinese FTS)
  index.md                    full-corpus index table
  raw/YYYY-MM-DD.txt          raw HTML fragment of the article (for offline rebuild)
  log/                        per-run logs

Commands
  sync     incremental crawl (default). --force re-downloads and compares sha;
           --limit N keeps only the N most recent issues
  rebuild  offline rebuild of md/jsonl/db from raw/ + front matter in existing md
  index    rebuild index.md
  verify   full-corpus consistency check (md / jsonl / db / noise / truncation);
           exits 1 if any issue is found
  stats    totals, yearly distribution, most active media
  search   FTS5 full-text search, e.g. search 九二共识 -n 10
  export   merge the corpus into a single markdown file

Design constraints
  * Zero third-party dependencies; Python 3.9+ (tested on 3.9 and 3.12)
  * All writes are atomic (temp file + os.replace); interruption leaves no partial file
  * Idempotent: re-crawling the same page produces byte-identical output
    (the sha is stored in front matter)
  * Corpus copyright belongs to the Taiwan Affairs Office; research/teaching only,
    commercial resale prohibited
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable

__version__ = '2.0.0'
__all__ = ['collect_index', 'article_html', 'paragraphs', 'polish',
           'split_blocks', 'extract_qa', 'build_record', 'record_to_md',
           'record_to_jsonl', 'sync', 'rebuild', 'verify']

BASE = 'https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/'
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
JSONL = os.path.join(DATA, 'jsonl')
RAW = os.path.join(HERE, 'raw')
LOG = os.path.join(HERE, 'log')
DB = os.path.join(HERE, 'gtb.db')
INDEX_MD = os.path.join(HERE, 'index.md')
MERGED = os.path.join(HERE, 'gtb_qa.jsonl')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
TIMEOUT = 30
RETRIES = 3
WORKERS = 6


# ============================ Utilities ============================
def sha16(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def atomic_write(path: str, text: str) -> None:
    """Atomic write: temp file in the same directory + os.replace."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def read_text(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def corpus_dates() -> list[str]:
    """All issue dates under data/, newest first; independent of --limit."""
    if not os.path.isdir(DATA):
        return []
    return sorted((f[:-3] for f in os.listdir(DATA) if f.endswith('.md')), reverse=True)


class _Tee:
    """Duplicate stdout/stderr to both the console and a log file."""

    def __init__(self, *streams) -> None:
        self.streams = [s for s in streams if s]

    def write(self, s: str) -> int:
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:          # e.g. terminal closed; must not break the pipeline
                pass
        return len(s)

    def flush(self) -> None:
        for st in self.streams:
            with contextlib.suppress(Exception):
                st.flush()

    def isatty(self) -> bool:
        return False


def setup_log(tag: str = '') -> str:
    os.makedirs(LOG, exist_ok=True)
    name = time.strftime('%Y%m%d-%H%M%S') + (f'-{tag}' if tag else '') + '.log'
    path = os.path.join(LOG, name)
    # Intentionally kept open for the whole process (tee target); the interpreter
    # closes it on exit.
    f = open(path, 'w', encoding='utf-8', buffering=1)  # noqa: SIM115
    if not isinstance(sys.stdout, _Tee):      # avoid wrapping twice (duplicate output)
        sys.stdout, sys.stderr = _Tee(sys.stdout, f), _Tee(sys.stderr, f)
    print(f'[log] {path}', file=sys.stderr, flush=True)
    return path


# ============================ Network ============================
def fetch(url: str, retries: int = RETRIES, timeout: int = TIMEOUT) -> bytes:
    """GET with linear backoff; 4xx (except 429) raises without retrying."""
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': BASE,
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:                # timeout / DNS / connection reset
            last = e
        time.sleep(1.5 * (i + 1))
    assert last is not None
    raise last


def get_text(url: str) -> str:
    """The site declares GBK; a few pages contain UTF-8 and would raise
    UnicodeDecodeError, so decode with errors='replace' as a fallback."""
    return fetch(url).decode('gbk', 'replace')


# ============================ Listing page ============================
ITEM_RE = re.compile(
    r'<li><span>\[ ?(\d{4}-\d{1,2}-\d{1,2}) ?\]</span>\s*'
    r'<a href="([^"]+)"[^>]*title="([^"]+)"')


def collect_index(max_pages: int = 40) -> list[dict]:
    """Return [{date, url, title}] in site order (newest first)."""
    items: list[dict] = []
    for page in range(max_pages):
        url = BASE + ('' if page == 0 else f'index_{page}.htm')
        try:
            h = get_text(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:                 # past the last page
                break
            raise
        found = ITEM_RE.findall(h)
        if not found:
            break
        for d, href, title in found:
            if href.startswith('/'):
                href = 'https://www.gwytb.gov.cn' + href
            elif not href.startswith('http'):
                href = urllib.parse.urljoin(BASE, href)
            items.append({'date': d, 'url': href, 'title': html.unescape(title)})
        print(f'  listing page {page}: {len(found)} issues', flush=True)
    return items


# ============================ Article page ============================
def parse_article(h: str) -> tuple[str, str, str]:
    """Extract (title, info, body_html) from an article page.

    Supports both template generations and is a pure function for easy testing.
    """
    i = h.find('TRS_Editor')
    if i < 0:
        i = h.find('contentArea')
        if i < 0:
            return '', '', ''
    i = h.rfind('<', 0, i)                    # back up to the tag start; drop 'TRS_Editor>'
    head = h[:i]
    m = re.search(r'<h1>(.*?)</h1>', head, re.S)
    title = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''
    m = re.search(r'<div class="info">(.*?)</div>', head, re.S)
    info = re.sub(r'<[^>]+>', ' ', m.group(1)).strip() if m else ''
    info = re.sub(r'\s+', ' ', html.unescape(info))
    body = h[i:]
    for cut in ('<!--翻页页码_begin-->', '<div id="pageNumber"'):
        if cut in body:
            body = body.split(cut)[0]
    body = body.rsplit('</div>', 1)[0]
    return title, info, body


def article_html(url: str) -> tuple[str, str, str]:
    return parse_article(get_text(url))


def paragraphs(chunk: str) -> list[str]:
    """Turn block tags into newlines; support both <p> and div/br/font templates;
    convert <b> to **."""
    chunk = re.sub(r'(?is)<(script|style).*?</\1>', '', chunk)
    chunk = re.sub(r'(?is)<(b|strong)[^>]*>(.*?)</\1>', r'@@B@@\2@@/B@@', chunk)
    chunk = re.sub(r'(?is)<(br|/p|/div|/tr|/h[1-6]|/li|/table)[^>]*>', '\n', chunk)
    chunk = re.sub(r'(?i)<(p|div|tr|h[1-6]|li|table)[^>]*>', '\n', chunk)
    chunk = re.sub(r'<[^>]+>', '', chunk)
    chunk = html.unescape(chunk).replace('\u3000', '').replace('\xa0', ' ')
    chunk = chunk.replace('@@B@@', '**').replace('@@/B@@', '**')
    out: list[str] = []
    for line in chunk.split('\n'):
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if not line or line in ('**', '****'):
            continue
        if out and line == out[-1]:           # duplicate adjacent lines from old pagination
            continue
        out.append(line)
    return out


TITLE_NOISE = {
    '国台办新闻发布会实录', '国务院台办新闻发布会实录',
    '国台办新闻发布会辑录', '国务院台办新闻发布会辑录',
    '国台办举行新闻发布会', '国务院台办举行新闻发布会',
}


def polish(paras: Iterable[str], title: str = '') -> list[str]:
    """Remove duplicated title/date lines and empty bold shells (<b></b>)."""
    outs: list[str] = []
    head = True
    t_title = (title or '').strip()
    for p in paras:
        p = re.sub(r'\*\*[ \t]*\*\*', '', p)     # empty bold shell
        p = re.sub(r'\*{3,}', '**', p).strip()
        t = p.strip().strip('*').strip()
        if not t:
            continue
        if head and (t in TITLE_NOISE or (t_title and t == t_title)):
            continue
        if head and re.fullmatch(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', t):
            continue
        head = False
        outs.append(p)
    return outs


# ============================ Q&A segmentation ============================
# Spokespersons (including former ones). A name not listed here is still inferred
# as a spokesperson if it recurs within a single article.
SPOKESPERSONS = {
    '张铭清', '李维一', '杨毅', '范丽青', '马晓光',
    '安峰山', '朱凤莲', '陈斌华', '张晗', '陈云林',
}
JOURNALIST_HINTS = (
    '记者', '日报', '晚报', '时报', '商报', '导报', '通讯社', '电视台', '电台',
    '广播', '周刊', '杂志', '新闻', '媒体', '观察', '评论', '通讯', '报', '社', '网',
)
# Two bold styles used by the site: '**name：**text' and '**name**：text'
BOLD_SPEAKER_RE = re.compile(
    r'^\*\*(?P<name>[^*\n]{1,40}?)(?:[：:]\*\*|\*\*[：:])\s*(?P<text>.*)$', re.S)
PLAIN_SPEAKER_RE = re.compile(
    r'^(?P<name>[^\s*：:，。；、！？“”]{2,14})[：:]\s*(?P<text>\S.*)$', re.S)


def classify(name: str) -> str:
    if name in SPOKESPERSONS:
        return 'spokesperson'
    if any(h in name for h in JOURNALIST_HINTS):
        return 'journalist'
    if name.endswith(('台办', '发言人', '主任', '局长')):
        return 'spokesperson'
    return 'other'


def split_blocks(paras: Iterable[str]) -> list[dict]:
    """Split paragraphs into [{name, role, text}].

    Untagged paragraphs are appended to the previous block as a continuation.
    role: spokesperson / journalist / other / body

    A plain-text 'name：' heading is treated as a speaker only when it occurs
    at least twice or contains a known name/media keyword. This avoids splitting
    on ordinary prose such as 'he said:'.
    """
    paras = list(paras)
    bold = [BOLD_SPEAKER_RE.match(p) for p in paras]
    plain = [None if b else PLAIN_SPEAKER_RE.match(p) for b, p in zip(bold, paras)]
    counts: dict[str, int] = {}
    for m in list(bold) + [m for m in plain if m]:
        if m:
            counts[m.group('name').strip().strip('*')] = counts.get(
                m.group('name').strip().strip('*'), 0) + 1

    blocks: list[dict] = []
    for p, mb, mp in zip(paras, bold, plain):
        m = mb or mp
        name = ''
        if m:
            name = m.group('name').strip().strip('*').strip()
            trusted = bool(mb) or name in SPOKESPERSONS or counts.get(name, 0) >= 2 \
                or any(h in name for h in JOURNALIST_HINTS)
            if not trusted or len(name) > 20:
                m, name = None, ''
        if m:
            blocks.append({'name': name, 'role': classify(name),
                           'text': m.group('text').strip()})
        elif blocks:
            blocks[-1]['text'] = (blocks[-1]['text'] + '\n' + p).strip()
        else:
            blocks.append({'name': '', 'role': 'body', 'text': p})

    # A name that recurs in one article and does not look like media is treated
    # as a spokesperson, so new names do not require code changes.
    for b in blocks:
        if b['role'] == 'other' and counts.get(b['name'], 0) >= 3:
            b['role'] = 'spokesperson'
    return blocks


def extract_qa(blocks: list[dict]) -> tuple[str, list[dict]]:
    """Pair journalist questions with spokesperson answers.

    Returns (opening, [{seq, asker, speaker, question, answer}]).
    """
    opening: list[str] = []
    qa: list[dict] = []
    cur: dict | None = None
    for b in blocks:
        if b['role'] == 'journalist':
            if cur is not None and cur['answer']:
                cur = None
            if cur is None:
                cur = {'seq': len(qa) + 1, 'asker': b['name'], 'speaker': '',
                       'question': b['text'], 'answer': ''}
                qa.append(cur)
            else:                               # merge consecutive follow-ups by the same journalist
                cur['question'] = (cur['question'] + '\n' + b['text']).strip()
            continue
        if cur is None:                         # before the first question -> opening remarks
            opening.append(b['text'])
            continue
        cur['answer'] = (cur['answer'] + '\n' + b['text']).strip()
        if not cur['speaker'] and b['name']:
            cur['speaker'] = b['name']

    for q in qa:
        q['question'] = q['question'].strip()
        q['answer'] = q['answer'].strip()
    return '\n'.join(opening).strip(), qa


# ============================ Record model ============================
INFO_RE = re.compile(
    r'(?P<published>\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)'
    r'\s*来源[:：]\s*(?P<org>.*)')


def parse_info(info: str) -> tuple[str, str]:
    m = INFO_RE.search(info or '')
    return (m.group('published').strip(), m.group('org').strip()) if m else ('', '')


def build_record(item: dict, title: str, info: str, paras: list[str]) -> dict:
    """Build a canonical record from cleaned paragraphs.

    This is the single source of truth for md/jsonl/db.
    """
    blocks = split_blocks(paras)
    opening, qa = extract_qa(blocks)
    published, org = parse_info(info)
    body = '\n\n'.join(paras)
    return {
        'date': item['date'],
        'title': (title or item['title']).strip().strip('"“”').strip(),
        'url': item['url'],
        'published': published,
        'organization': org,
        'paragraphs': len(paras),
        'chars': sum(len(p) for p in paras),
        'sha': sha16(body),
        'opening': opening,
        'qa': qa,
        'body': body,
    }


def record_to_md(rec: dict) -> str:
    t = rec['title'].replace('"', '\\"')
    fm = ['---',
          f'source: {rec["url"]}',
          f'date: {rec["date"]}',
          f'title: "{t}"',
          f'published: {rec["published"]}',
          f'organization: {rec["organization"]}',
          f'paragraphs: {rec["paragraphs"]}',
          f'chars: {rec["chars"]}',
          f'qa: {len(rec["qa"])}',
          f'sha: {rec["sha"]}',
          '---', '']
    info = f'> 发布：{rec["published"]} 来源：{rec["organization"]}'.strip()
    head = [info if rec['published'] else '',
            f'> 原文：{rec["url"]}', '', '---', '']
    return '\n'.join(fm + [f'# {rec["title"]}', ''] + head +
                     [rec['body'], '']).rstrip() + '\n'


def md_to_record(text: str, date: str) -> dict | None:
    """Parse markdown back into a record (used by rebuild).

    Reads front matter and body paragraphs.
    """
    m = re.match(r'^---\n(.*?)\n---\n\n(.*)$', text, re.S)
    if not m:
        return None
    meta = {k: _unquote(v) for k, v in re.findall(r'^(\w+):[ \t]*(.*)$', m.group(1), re.M)}
    # Strip the title, blockquote lines, and separators line by line; the rest is
    # the body. Do not split on blank lines here: that would stop at the first
    # blank line.
    lines = m.group(2).split('\n')
    i = 0
    while i < len(lines) and (not lines[i].strip()
                              or lines[i].startswith('#')
                              or lines[i].startswith('>')
                              or lines[i].strip() == '---'):
        i += 1
    body_md = '\n'.join(lines[i:])
    paras = [p.strip() for p in body_md.split('\n\n') if p.strip()]
    item = {'date': date, 'url': meta.get('source', ''), 'title': meta.get('title', '')}
    if not meta.get('published'):
        pm = re.search(r'^> 发布：(.+)$', text, re.M)     # legacy layout: metadata in blockquote
        if pm:
            meta['published'], meta['organization'] = parse_info(pm.group(1))
    info = f'{meta.get("published", "")} 来源：{meta.get("organization", "")}'
    return build_record(item, meta.get('title', ''), info, paras)


def record_to_jsonl(rec: dict) -> str:
    lines = [json.dumps({'type': 'conference', 'date': rec['date'], 'title': rec['title'],
                         'url': rec['url'], 'published': rec['published'],
                         'organization': rec['organization'],
                         'paragraphs': rec['paragraphs'], 'chars': rec['chars'],
                         'qa': len(rec['qa']), 'sha': rec['sha']},
                        ensure_ascii=False)]
    for q in rec['qa']:
        lines.append(json.dumps({'type': 'qa', 'date': rec['date'], 'seq': q['seq'],
                                 'asker': q['asker'], 'speaker': q['speaker'],
                                 'question': q['question'], 'answer': q['answer']},
                                ensure_ascii=False))
    return '\n'.join(lines) + '\n'


# ============================ Storage: SQLite ============================
SCHEMA = """
CREATE TABLE IF NOT EXISTS conference(
  date         TEXT PRIMARY KEY,
  title        TEXT NOT NULL,
  url          TEXT NOT NULL,
  published    TEXT,
  organization TEXT,
  paragraphs   INTEGER,
  chars        INTEGER,
  sha          TEXT,
  qa_count     INTEGER,
  fetched_at   TEXT,
  updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS qa(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  date     TEXT NOT NULL,
  seq      INTEGER NOT NULL,
  asker    TEXT,
  speaker  TEXT,
  question TEXT NOT NULL,
  answer   TEXT NOT NULL,
  UNIQUE(date, seq)
);
CREATE INDEX IF NOT EXISTS ix_qa_date ON qa(date);
CREATE VIRTUAL TABLE IF NOT EXISTS qa_fts USING fts5(
  asker, speaker, question, answer,
  content='qa', content_rowid='id', tokenize='trigram'
);
"""


def db_connect(path: str | None = None) -> sqlite3.Connection:
    path = path or DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    if path != ':memory:':
        conn.executescript(SCHEMA)
    return conn


def db_upsert(conn: sqlite3.Connection, rec: dict, fetched_at: str = '') -> None:
    """Replace one issue atomically (delete then insert) for idempotent reruns."""
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        'INSERT INTO conference(date,title,url,published,organization,paragraphs,'
        'chars,sha,qa_count,fetched_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(date) DO UPDATE SET title=excluded.title, url=excluded.url, '
        'published=excluded.published, organization=excluded.organization, '
        'paragraphs=excluded.paragraphs, chars=excluded.chars, sha=excluded.sha, '
        'qa_count=excluded.qa_count, fetched_at=COALESCE(NULLIF(excluded.fetched_at,\'\'),'
        'conference.fetched_at), updated_at=excluded.updated_at',
        (rec['date'], rec['title'], rec['url'], rec['published'], rec['organization'],
         rec['paragraphs'], rec['chars'], rec['sha'], len(rec['qa']),
         fetched_at, now))
    old_ids = [r[0] for r in conn.execute('SELECT id FROM qa WHERE date=?', (rec['date'],))]
    # External-content FTS: delete index rows by rowid first (the qa rows still
    # exist so fts5 can read the old values), then delete the qa rows.
    conn.executemany('DELETE FROM qa_fts WHERE rowid=?', [(i,) for i in old_ids])
    conn.execute('DELETE FROM qa WHERE date=?', (rec['date'],))
    for q in rec['qa']:
        cur = conn.execute('INSERT INTO qa(date,seq,asker,speaker,question,answer) '
                           'VALUES(?,?,?,?,?,?)',
                           (rec['date'], q['seq'], q['asker'], q['speaker'],
                            q['question'], q['answer']))
        conn.execute('INSERT INTO qa_fts(rowid,asker,speaker,question,answer) '
                     'VALUES(?,?,?,?,?)',
                     (cur.lastrowid, q['asker'], q['speaker'], q['question'], q['answer']))


def db_sha(conn: sqlite3.Connection, date: str) -> str:
    row = conn.execute('SELECT sha FROM conference WHERE date=?', (date,)).fetchone()
    return row['sha'] if row else ''


def db_search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """Search Q&A pairs. Space-separated terms are ANDed; short terms (<3 chars)
    automatically fall back to LIKE because the trigram tokenizer needs 3 chars.
    """
    tokens = query.split()
    if not tokens:
        return []
    cols = 'qa.date, qa.seq, qa.asker, qa.speaker, qa.question, qa.answer'
    if all(len(t) >= 3 for t in tokens):      # trigram needs at least 3 characters
        sql = (f'SELECT {cols} FROM qa_fts JOIN qa ON qa.id = qa_fts.rowid '
               'WHERE qa_fts MATCH ? ORDER BY qa.date DESC, qa.seq LIMIT ?')
        match = ' '.join('"' + t.replace('"', '""') + '"' for t in tokens)
        try:
            rows = conn.execute(sql, (match, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    else:                                     # short term present: intersect per-term LIKE
        where = ' AND '.join(['(qa.question LIKE ? OR qa.answer LIKE ?)'] * len(tokens))
        params: list[str] = []
        for t in tokens:
            params += [f'%{t}%', f'%{t}%']
        rows = conn.execute(
            f'SELECT {cols} FROM qa WHERE {where} ORDER BY qa.date DESC, qa.seq LIMIT ?',
            (*params, limit)).fetchall()
    return [dict(r) for r in rows]


# ============================ Storage: files ============================
def md_path(date: str) -> str:
    return os.path.join(DATA, f'{date}.md')


def jsonl_path(date: str) -> str:
    return os.path.join(JSONL, f'{date}.jsonl')


def raw_path(date: str) -> str:
    return os.path.join(RAW, f'{date}.txt')


def save_record(rec: dict) -> None:
    atomic_write(md_path(rec['date']), record_to_md(rec))
    atomic_write(jsonl_path(rec['date']), record_to_jsonl(rec))


def artifact_status(rec: dict) -> str:
    """Repair missing jsonl/raw artifacts for a cached record (offline)."""
    fixed = []
    if not os.path.exists(jsonl_path(rec['date'])):
        atomic_write(jsonl_path(rec['date']), record_to_jsonl(rec))
        fixed.append('jsonl')
    if not os.path.exists(raw_path(rec['date'])):
        fixed.append('raw')
    return '+'.join(fixed)


def write_index(rows: list[str] | None = None) -> int:
    rows = rows or corpus_dates()
    head = ['# Taiwan Affairs Office Press Conference Corpus · Index', '',
            f'- Issues: {len(rows)}',
            f'- Range: {rows[-1]} ~ {rows[0]}' if rows else '- Range: -',
            f'- Source: {BASE}',
            f'- Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}', '',
            '| Date | File | Paragraphs | Characters | Q&A |', '|---|---|---|---|---|']
    body = []
    total = qa_total = 0
    for d in rows:
        try:
            text = read_text(md_path(d))
            m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
            meta = dict(re.findall(r'^(\w+):[ \t]*(.*)$', m.group(1), re.M)) if m else {}
            paragraphs, chars = int(meta.get('paragraphs', 0)), int(meta.get('chars', 0))
            nqa = int(meta.get('qa', 0))
        except Exception:
            paragraphs = chars = nqa = 0
        total += chars
        qa_total += nqa
        body.append(f'| {d} | [{d}.md](data/{d}.md) | {paragraphs} | {chars:,} | {nqa} |')
    tail = ['', f'Total {total:,} characters (whitespace removed) · '
                f'{qa_total:,} Q&A pairs', '']
    atomic_write(INDEX_MD, '\n'.join(head + body + tail))
    return len(rows)


# ============================ Pipeline ============================
HTML_LEAK_RE = re.compile(r'</?(?:div|span|p|br|font|b|table|tr|td)\b', re.I)


def process_one(item: dict, force: bool = False, dry: bool = False) -> dict:
    """Process one issue: parse cache offline if present, otherwise download."""
    date, url = item['date'], item['url']
    out = md_path(date)

    if not force and os.path.exists(out):
        rec = md_to_record(read_text(out), date)
        if rec is None:                        # corrupted front matter -> re-fetch
            force = True
        else:
            rec['url'] = rec['url'] or url
            fixed = ''
            if not dry:
                fixed = artifact_status(rec)
            return {'date': date, 'url': url, 'rec': rec, 'err': '',
                    'status': 'cached' + (f'+{fixed}' if fixed else '')}

    try:
        title, info, body = article_html(url)
    except Exception as e:
        return {'date': date, 'url': url, 'rec': None, 'status': 'FAIL',
                'err': f'{type(e).__name__}: {e}'}
    if not body.strip():
        return {'date': date, 'url': url, 'rec': None, 'status': 'EMPTY',
                'err': 'no TRS_Editor/contentArea'}
    paras = polish(paragraphs(body), title)
    if not paras:
        return {'date': date, 'url': url, 'rec': None, 'status': 'EMPTY',
                'err': 'no paragraphs'}
    rec = build_record(item, title, info, paras)

    text = record_to_md(rec)
    old = read_text(out) if os.path.exists(out) else ''
    # Compare rendered output: any change to body or metadata triggers a rewrite,
    # which keeps the operation idempotent.
    status = 'new' if not old else ('same' if old == text else 'updated')
    if not dry and status != 'same':
        atomic_write(raw_path(date), body)
        save_record(rec)
    return {'date': date, 'url': url, 'rec': rec, 'err': '', 'status': status}


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it['date'] in seen:                 # same date listed twice
            continue
        seen.add(it['date'])
        out.append(it)
    return out


def _write_merged(conn: sqlite3.Connection | None = None) -> int:
    """Write gtb_qa.jsonl: all Q&A pairs, date ascending and seq ascending."""
    lines, n = [], 0
    for d in sorted(corpus_dates()):
        try:
            rec = md_to_record(read_text(md_path(d)), d)
        except Exception:
            continue
        if not rec:
            continue
        for q in rec['qa']:
            lines.append(json.dumps({'type': 'qa', 'date': d, 'seq': q['seq'],
                                     'asker': q['asker'], 'speaker': q['speaker'],
                                     'question': q['question'], 'answer': q['answer']},
                                    ensure_ascii=False))
            n += 1
    atomic_write(MERGED, '\n'.join(lines) + '\n' if lines else '')
    return n


def _report(rows: list[dict], conn: sqlite3.Connection | None) -> dict:
    dates = corpus_dates()
    rep = {
        'run': {'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'ok': len([r for r in rows if r['status'] in ('new', 'updated', 'same')]),
                'cached': len([r for r in rows if r['status'].startswith('cached')]),
                'bad': [{'date': r['date'], 'status': r['status'], 'err': r['err']}
                        for r in rows if r['status'] in ('FAIL', 'EMPTY')]},
        'corpus': {'conferences': len(dates),
                   'range': [dates[-1], dates[0]] if dates else []},
    }
    if conn is not None:
        row = conn.execute('SELECT COUNT(*) n, COALESCE(SUM(chars),0) c, '
                           'COALESCE(SUM(qa_count),0) q FROM conference').fetchone()
        rep['corpus'].update({'conferences_in_db': row['n'], 'chars': row['c'],
                              'qa_pairs': row['q']})
    atomic_write(os.path.join(HERE, 'report.json'),
                 json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


def sync(limit: int | None = None, force: bool = False, since: str = '',
         workers: int = WORKERS, dry: bool = False) -> int:
    print('[1/3] Fetching listing ...', flush=True)
    items = _dedupe(collect_index())
    if since:
        items = [it for it in items if it['date'] >= since]
    if limit:
        items = items[:limit]
    if not items:
        print('  listing is empty', flush=True)
        return 1
    print(f'      {len(items)} issues ({items[-1]["date"]} ~ {items[0]["date"]})', flush=True)

    print('[2/3] Fetching and cleaning articles ...', flush=True)
    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(process_one, it, force, dry): it for it in items}
        for n, fut in enumerate(cf.as_completed(futs), 1):
            it = futs[fut]
            try:
                r = fut.result()
            except Exception as e:             # unhandled exception inside the worker
                r = {'date': it['date'], 'url': it['url'], 'rec': None,
                     'status': 'FAIL', 'err': f'{type(e).__name__}: {e}'}
            results.append(r)
            if n % 25 == 0 or n == len(items):
                print(f'      {n}/{len(items)} {r["date"]} {r["status"]}', flush=True)

    print('[3/3] Writing database and index ...', flush=True)
    conn = None
    nqa = 0
    if not dry:
        conn = db_connect()
        for r in results:
            if r['rec']:
                db_upsert(conn, r['rec'])
        conn.commit()
        nqa = _write_merged(conn)
        write_index()
    bad = [r for r in results if r['status'] in ('FAIL', 'EMPTY')]
    print(f'      run: new {len([r for r in results if r["status"] == "new"])}, '
          f'updated {len([r for r in results if r["status"] == "updated"])}, '
          f'same {len([r for r in results if r["status"] == "same"])}, '
          f'cached {len([r for r in results if r["status"].startswith("cached")])}, '
          f'failed {len(bad)}', flush=True)
    if not dry:
        print(f'      {nqa:,} Q&A pairs · index {INDEX_MD}', flush=True)
        _report(results, conn)
        conn.close()
    for b in bad[:10]:
        print(f'  error: {b["date"]} {b["status"]} {b["err"]}', flush=True)
    return 1 if bad else 0


def rebuild(dry: bool = False) -> int:
    """Rebuild offline: raw/ HTML is authoritative for the body; markdown front
    matter provides metadata.
    """
    dates = corpus_dates()
    print(f'[rebuild] {len(dates)} issues (offline)', flush=True)
    conn = None if dry else db_connect()
    ok = skip = from_raw = 0
    for d in dates:
        meta = _frontmatter(read_text(md_path(d)))
        item = {'date': d, 'url': meta.get('source', ''), 'title': meta.get('title', '')}
        info = f'{meta.get("published", "")} 来源：{meta.get("organization", "")}'
        rec = None
        if os.path.exists(raw_path(d)):
            paras = polish(paragraphs(read_text(raw_path(d))), item['title'])
            if paras:
                rec = build_record(item, item['title'], info, paras)
                from_raw += 1
        if rec is None:                       # no raw snapshot: fall back to markdown body
            rec = md_to_record(read_text(md_path(d)), d)
        if rec is None:
            print(f'  skip {d}: no raw and markdown is unparseable', flush=True)
            skip += 1
            continue
        rec['url'] = rec['url'] or item['url']
        if not dry:
            save_record(rec)
            db_upsert(conn, rec)
        ok += 1
    nqa = 0
    if not dry:
        conn.commit()
        nqa = _write_merged(conn)
        conn.close()
        write_index()
    print(f'  {ok} issues generated ({from_raw} from raw/), {skip} skipped, '
          f'{nqa:,} Q&A pairs', flush=True)
    return 1 if skip else 0


# ============================ Verify / stats / search ============================
def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1].replace('\\"', '"').replace("\\'", "'")
    return v


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not m:
        return {}
    return {k: _unquote(v) for k, v in re.findall(r'^(\w+):[ \t]*(.*)$', m.group(1), re.M)}


def verify(fix: bool = False) -> int:
    dates = corpus_dates()
    conn = db_connect()
    issues: list[tuple[str, str]] = []
    warnings = 0
    no_raw: list[str] = []
    for d in dates:
        text = read_text(md_path(d))
        meta = _frontmatter(text)
        rec = md_to_record(text, d)
        if not rec:
            issues.append((d, 'md-unparsable'))
            continue
        if meta.get('sha') != rec['sha']:
            issues.append((d, 'sha-mismatch'))
        if str(rec['chars']) != meta.get('chars', '').strip():
            issues.append((d, 'chars-mismatch'))
        if str(len(rec['qa'])) != meta.get('qa', '').strip():
            issues.append((d, 'qa-count-mismatch'))
        if HTML_LEAK_RE.search(rec['body']) or '&nbsp;' in rec['body']:
            issues.append((d, 'html-remnant'))
        if '****' in rec['body'] or '\u3000' in rec['body']:
            issues.append((d, 'noise'))
        if len(rec['body']) < 100:
            issues.append((d, 'too-short'))
        warnings += sum(1 for q in rec['qa'] if not q['answer'] or not q['question'])
        if not os.path.exists(raw_path(d)):
            no_raw.append(d)

        jl = jsonl_path(d)
        if not os.path.exists(jl):
            issues.append((d, 'jsonl-missing'))
        else:
            lines = [ln for ln in read_text(jl).split('\n') if ln.strip()]
            if len(lines) != len(rec['qa']) + 1:
                issues.append((d, 'jsonl-count'))
            elif [json.loads(x)['seq'] for x in lines[1:]] != list(range(1, len(rec['qa']) + 1)):
                issues.append((d, 'jsonl-seq'))

        row = conn.execute('SELECT sha,qa_count FROM conference WHERE date=?', (d,)).fetchone()
        if not row:
            issues.append((d, 'db-missing'))
        elif row['sha'] != rec['sha']:
            issues.append((d, 'db-sha'))
        elif row['qa_count'] != len(rec['qa']):
            issues.append((d, 'db-qa-count'))

        if fix and any(i[1] in ('sha-mismatch', 'chars-mismatch', 'qa-count-mismatch',
                                'jsonl-missing', 'jsonl-count', 'jsonl-seq',
                                'db-missing', 'db-sha', 'db-qa-count') for i in issues):
            save_record(rec)
            db_upsert(conn, rec)

    dbn = conn.execute('SELECT COUNT(*) n FROM conference').fetchone()['n']
    qan = conn.execute('SELECT COUNT(*) n FROM qa').fetchone()['n']
    ftsn = conn.execute('SELECT COUNT(*) n FROM qa_fts').fetchone()['n']
    if dbn != len(dates):
        issues.append(('-', f'db-row-count({dbn}!={len(dates)})'))
    if ftsn != qan:
        issues.append(('-', f'fts-count({ftsn}!={qan})'))
    conn.commit()
    conn.close()

    print(f'[verify] {len(dates)} issues · db {dbn} / {qan:,} Q&A / fts {ftsn:,}')
    if warnings:
        print(f'  note: {warnings} Q&A pairs have an empty question or answer '
              f'(common in early press-release style)')
    if no_raw:
        print(f'  note: {len(no_raw)} issues lack a raw/ snapshot '
              f'(rebuild can only fall back to markdown): '
              f'{", ".join(no_raw[:5])}{" …" if len(no_raw) > 5 else ""}')
    if not issues:
        print('  ✅ all checks passed')
        return 0
    kinds: dict[str, list[str]] = {}
    for d, k in issues:
        kinds.setdefault(k, []).append(d)
    print(f'  ❌ {len(issues)} issue(s):')
    for k, ds in sorted(kinds.items()):
        print(f'    {k}: {len(ds)} occurrence(s), e.g. {" ".join(ds[:5])}')
    return 1


def stats() -> None:
    conn = db_connect()
    row = conn.execute('SELECT COUNT(*) n, SUM(chars) c, SUM(qa_count) q '
                       'FROM conference').fetchone()
    print(f'Issues {row["n"]} · body {int(row["c"] or 0):,} chars · '
          f'Q&A {int(row["q"] or 0):,} pairs')
    print('\nBy year:')
    for r in conn.execute("SELECT substr(date,1,4) y, COUNT(*) n, SUM(qa_count) q, "
                          "SUM(chars) c FROM conference GROUP BY y ORDER BY y DESC"):
        print(f'  {r["y"]}  {r["n"]:>3} issues  {r["q"] or 0:>4} Q&A  '
              f'{int(r["c"] or 0):>8,} chars')
    print('\nTop 10 outlets by questions:')
    for r in conn.execute('SELECT asker, COUNT(*) n FROM qa WHERE asker<>\'\' '
                          'GROUP BY asker ORDER BY n DESC LIMIT 10'):
        print(f'  {r["n"]:>4}  {r["asker"]}')
    print('\nTop speakers by answers:')
    for r in conn.execute('SELECT speaker, COUNT(*) n FROM qa WHERE speaker<>\'\' '
                          'GROUP BY speaker ORDER BY n DESC LIMIT 10'):
        print(f'  {r["n"]:>4}  {r["speaker"]}')
    conn.close()


def search(query: str, limit: int = 10, as_json: bool = False) -> int:
    conn = db_connect()
    rows = db_search(conn, query, limit)
    conn.close()
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0 if rows else 1
    if not rows:
        print(f'No results: {query}')
        return 1
    for i, r in enumerate(rows, 1):
        print(f'\n[{i}] {r["date"]} #{r["seq"]}  {r["asker"] or "?"} → {r["speaker"] or "?"}')
        print(f'  Q: {r["question"][:160]}')
        print(f'  A: {r["answer"][:200]}')
    print(f'\n{len(rows)} result(s)')
    return 0


def export(out: str = '') -> int:
    out = out or os.path.join(HERE, 'gtb_all.md')
    dates = corpus_dates()
    body = []
    for d in dates:
        rec = md_to_record(read_text(md_path(d)), d)
        if rec:
            body.append(rec['body'].strip())
    text = ('# Taiwan Affairs Office Press Conference Transcripts\n\n'
            f'> {len(body)} issues · source: {BASE}\n'
            f'> Copyright belongs to the Taiwan Affairs Office; research/teaching only\n\n'
            + '\n\n---\n\n'.join(body) + '\n')
    atomic_write(out, text)
    print(f'Exported {len(body)} issues -> {out} '
          f'({os.path.getsize(out) / 1e6:.2f} MB)')
    return 0


# ============================ CLI ============================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='scrape_gtb.py',
        description='Taiwan Affairs Office press-conference corpus collector and rebuilder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples: python scrape_gtb.py sync --limit 5\n'
               '          python scrape_gtb.py search 九二共识 -n 5\n'
               '          python scrape_gtb.py verify')
    p.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    p.add_argument('--no-log', action='store_true', help='do not write log/ files')
    sub = p.add_subparsers(dest='cmd')

    s = sub.add_parser('sync', help='incremental crawl (default)')
    s.add_argument('--limit', type=int, help='process only the N most recent issues')
    s.add_argument('--force', action='store_true', help='ignore cache and re-download')
    s.add_argument('--since', default='', help='only crawl issues on/after YYYY-MM-DD')
    s.add_argument('--workers', type=int, default=WORKERS)
    s.add_argument('--dry-run', action='store_true',
                   help='fetch and parse without writing (preview changes)')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('rebuild', help='rebuild md/jsonl/db offline (no network)')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('index', help='rebuild index.md')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('verify', help='verify consistency across the whole corpus')
    s.add_argument('--fix', action='store_true',
                   help='repair jsonl/db from markdown where possible')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('stats', help='show corpus statistics')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('search', help='full-text search')
    s.add_argument('query')
    s.add_argument('-n', '--limit', type=int, default=10)
    s.add_argument('--json', action='store_true', dest='as_json')
    s.add_argument('--no-log', action='store_true')

    s = sub.add_parser('export', help='merge all issues into one markdown file')
    s.add_argument('--out', default='')
    s.add_argument('--no-log', action='store_true')
    return p


CMDS = ('sync', 'rebuild', 'index', 'verify', 'stats', 'search', 'export')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--rebuild':        # v1 compatibility
        argv[0] = 'rebuild'
    if (argv and argv[0].startswith('-')
            and argv[0] not in ('-h', '--help', '--version')):
        argv.insert(0, 'sync')                 # v1 compatibility: bare flags mean sync
    elif not argv:
        argv = ['sync']
    args = build_parser().parse_args(argv)
    if not getattr(args, 'no_log', False):
        setup_log(args.cmd)

    if args.cmd == 'sync':
        return sync(args.limit, args.force, args.since, args.workers, args.dry_run)
    if args.cmd == 'rebuild':
        return rebuild(args.dry_run)
    if args.cmd == 'index':
        n = write_index()
        print(f'Index: {INDEX_MD} ({n} issues)')
        return 0
    if args.cmd == 'verify':
        return verify(args.fix)
    if args.cmd == 'stats':
        stats()
        return 0
    if args.cmd == 'search':
        return search(args.query, args.limit, args.as_json)
    if args.cmd == 'export':
        return export(args.out)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\ninterrupted', file=sys.stderr)
        sys.exit(130)
    except Exception:
        import traceback
        traceback.print_exc()
        print(f'[fail] see the log directory: {LOG}', file=sys.stderr)
        sys.exit(1)
