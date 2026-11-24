#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taiwan Affairs Office press-conference transcript corpus: full crawl + clean -> Markdown

Source: https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/
Listing: 50 items/page, index_1.htm ... index_N.htm
Articles: GBK encoded; body inside <div class=TRS_Editor>, one <p> per paragraph,
speakers marked with <b>

Usage:
    python scrape_gtb.py              # full crawl (cached, rerunnable/incremental)
    python scrape_gtb.py --limit 5    # crawl only the latest 5 issues, for testing
"""
import argparse, concurrent.futures as cf, html, json, os, re, sys, time
import urllib.request, urllib.error, urllib.parse

BASE = 'https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/'
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
RAW = os.path.join(HERE, 'raw')
LOG = os.path.join(HERE, 'log')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

ITEM_RE = re.compile(r'<li><span>\[ ([\d-]{8,10}) \]</span>\s*<a href="([^"]+)"[^>]*title="([^"]+)"')



class _Tee:
    """Tee output to both the console and the log file."""
    def __init__(self, *streams):
        self.streams = [x for x in streams if x]

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def setup_log(tag=''):
    """Log to log/<timestamp>[-tag].log and return the path."""
    os.makedirs(LOG, exist_ok=True)
    name = time.strftime('%Y%m%d-%H%M%S') + (f'-{tag}' if tag else '') + '.log'
    path = os.path.join(LOG, name)
    f = open(path, 'w', encoding='utf-8', buffering=1)
    if not isinstance(sys.stdout, _Tee):        # avoid double-wrapping -> duplicated output
        out, err = sys.stdout, sys.stderr
        sys.stdout = _Tee(out, f)
        sys.stderr = _Tee(err, f)
    print(f'[log] {path}', flush=True)
    return path


def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:      # network hiccup / transient 5xx
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def get_text(url):
    return fetch(url).decode('gbk', 'replace')


# ---------------- Listing ----------------
def collect_index():
    """Return [{date,url,title}] in site order (newest first)."""
    items, page = [], 0
    while True:
        url = BASE + ('' if page == 0 else f'index_{page}.htm')
        try:
            h = get_text(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
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
        page += 1
    return items


# ---------------- Article ----------------
def article_html(url):
    h = get_text(url)
    i = h.find('TRS_Editor')
    if i < 0:                       # old template: <div id="contentArea"> + div.Custom_UnionStyle
        i = h.find('contentArea')
        if i < 0:
            return '', '', ''
    i = h.rfind('<', 0, i)          # back up to the tag start; drop the 'TRS_Editor>' remnant
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


def paragraphs(chunk):
    """Generic segmentation: block tags -> newlines; supports the new template
    (p) and the old one (div/br/font).
    """
    chunk = re.sub(r'(?is)<(script|style).*?</\1>', '', chunk)
    chunk = re.sub(r'(?is)<(b|strong)[^>]*>(.*?)</\1>', r'@@B@@\2@@/B@@', chunk)
    chunk = re.sub(r'(?is)<(br|/p|/div|/tr|/h[1-6]|/li|/table)[^>]*>', '\n', chunk)
    chunk = re.sub(r'(?i)<(p|div|tr|h[1-6]|li|table)[^>]*>', '\n', chunk)
    chunk = re.sub(r'<[^>]+>', '', chunk)
    chunk = html.unescape(chunk).replace('\u3000', '').replace('\xa0', ' ')
    chunk = chunk.replace('@@B@@', '**').replace('@@/B@@', '**')
    out = []
    for line in chunk.split('\n'):
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if not line or line in ('**', '****'):
            continue
        if out and line == out[-1]:          # drop adjacent duplicate lines
            continue
        out.append(line)
    return out



TITLE_NOISE = {'国台办新闻发布会实录', '国务院台办新闻发布会实录',
               '国台办新闻发布会辑录', '国务院台办新闻发布会辑录'}


def polish(paras, title, date):
    """Strip noise from the body: duplicated title/date lines, empty bold shells, etc."""
    outs, head = [], True
    for p in paras:
        p = re.sub(r'\*\*[ \t]*\*\*', '', p)      # leftover empty bold <b></b>
        p = re.sub(r'\*{3,}', '**', p).strip()
        t = p.strip().strip('*').strip()
        if not t or t in ('', '**'):
            continue
        if head and (t in TITLE_NOISE or t == (title or '').strip()): 
            continue
        if head and re.fullmatch(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', t):
            continue
        head = False
        outs.append(p)
    return outs


def build_md(item, title, info, paras):
    date = item['date']
    head = [f'> 发布：{info}' if info else '', f'> 原文：{item["url"]}']
    lines = ['---',
             f'source: {item["url"]}',
             f'date: {date}',
             f'title: "{title or item["title"]}"',
             f'paragraphs: {len(paras)}',
             f'chars: {sum(len(p) for p in paras)}',
             '---', '',
             f'# {title or item["title"]}', '',
             *[h for h in head if h], '',
             '---', '']
    for p in paras:
        lines.append(p)
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def scrape_one(item, force=False):
    date = item['date']
    out = os.path.join(DATA, f'{date}.md')
    if os.path.exists(out) and not force:
        return {'date': date, 'status': 'cached', 'url': item['url']}
    try:
        title, info, body = article_html(item['url'])
        paras = paragraphs(body)
        paras = polish(paras, title, date)
        if not paras:
            return {'date': date, 'status': 'EMPTY', 'url': item['url']}
        os.makedirs(RAW, exist_ok=True)
        with open(os.path.join(RAW, f'{date}.txt'), 'w', encoding='utf-8') as f:
            f.write(body)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(build_md(item, title, info, paras))
        return {'date': date, 'status': 'ok', 'url': item['url'],
                'paras': len(paras), 'chars': sum(len(p) for p in paras)}
    except Exception as e:
        return {'date': date, 'status': 'FAIL', 'url': item['url'], 'err': repr(e)[:120]}


def corpus_rows():
    """Use the actual files under data/, independent of --limit."""
    ds = [f[:-3] for f in os.listdir(DATA) if f.endswith('.md')]
    return sorted(ds, reverse=True)


def write_index(rows=None):
    rows = rows or corpus_rows()
    idx = ['# Taiwan Affairs Office Press Conference Corpus · Index', '',
           f'- Issues: {len(rows)}',
           f'- Range: {rows[-1]} ~ {rows[0]}' if rows else '- Range: -',
           f'- Source: {BASE}',
           f'- Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}', '',
           '| Date | File | Paragraphs | Characters |', '|---|---|---|---|']
    for d in rows:
        p = os.path.join(DATA, f'{d}.md')
        n = c = 0
        if os.path.exists(p):
            t = open(p, encoding='utf-8').read()
            m1 = re.search(r'^paragraphs: (\d+)$', t, re.M)
            m2 = re.search(r'^chars: (\d+)$', t, re.M)
            n = int(m1.group(1)) if m1 else 0
            c = int(m2.group(1)) if m2 else 0
        idx.append(f'| {d} | [{d}.md](data/{d}.md) | {n} | {c} |')
    open(os.path.join(HERE, 'index.md'), 'w', encoding='utf-8').write('\n'.join(idx) + '\n')
    print(f'Index: {os.path.join(HERE, "index.md")} ({len(rows)} issues)')


def rebuild():
    """Offline rebuild: re-clean the original bodies from raw/ without network access."""
    rows = []
    for fn in sorted(os.listdir(RAW)):
        if not fn.endswith('.txt'):
            continue
        date = fn[:-4]
        md = os.path.join(DATA, f'{date}.md')
        title = url = info = ''
        if os.path.exists(md):
            t = open(md, encoding='utf-8').read()
            m = re.search(r'^title: "(.*)"$', t, re.M)
            title = m.group(1) if m else ''
            m = re.search(r'^source: (\S+)$', t, re.M)
            url = m.group(1) if m else ''
            m = re.search(r'^> 发布：(.*)$', t, re.M)
            info = m.group(1) if m else ''
        body = open(os.path.join(RAW, fn), encoding='utf-8').read()
        paras = polish(paragraphs(body), title, date)
        if not paras:
            continue
        item = {'date': date, 'url': url, 'title': title}
        open(md, 'w', encoding='utf-8').write(build_md(item, title, info, paras))
        rows.append(date)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--rebuild', action='store_true', help='offline: rebuild from raw/')
    a = ap.parse_args()

    setup_log('rebuild' if a.rebuild else 'crawl')
    os.makedirs(DATA, exist_ok=True)
    if a.rebuild:
        rows = rebuild()
        write_index(sorted(rows, reverse=True))
        print(f'[rebuild] regenerating {len(rows)} articles')
        return
    print('[1/3] Fetching listing ...', flush=True)
    items = collect_index()
    # Dedupe (a date may be listed twice); keep the first occurrence (newer position)
    seen, uniq = set(), []
    for it in items:
        if it['date'] in seen:
            continue
        seen.add(it['date'])
        uniq.append(it)
    if a.limit:
        uniq = uniq[:a.limit]
    print(f'      {len(items)} items, {len(uniq)} unique issues after dedupe '
          f'({uniq[-1]["date"]} ~ {uniq[0]["date"]})', flush=True)

    print('[2/3] Fetching and cleaning articles ...', flush=True)
    res = []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(scrape_one, it, a.force): it for it in uniq}
        for n, fu in enumerate(cf.as_completed(futs), 1):
            r = fu.result()
            res.append(r)
            if r['status'] not in ('ok', 'cached') or n % 25 == 0:
                print(f'      {n}/{len(uniq)} {r["date"]} {r["status"]}', flush=True)

    ok = [r for r in res if r['status'] == 'ok']
    bad = [r for r in res if r['status'] in ('FAIL', 'EMPTY')]
    total_chars = sum(r.get('chars', 0) for r in ok)
    print(f'[3/3] done: {len(ok)} new/updated, {len(bad)} failed/empty, '
          f'{total_chars:,} body characters this run', flush=True)

    rows = sorted(set(x['date'] for x in res), reverse=True)
    write_index()

    allrows = corpus_rows()
    json.dump({'run': {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'ok': len(ok),
                       'bad': bad, 'dates': rows},
               'corpus': {'total': len(allrows), 'range': [allrows[-1], allrows[0]]}},
              open(os.path.join(HERE, 'report.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    for b in bad[:10]:
        print('  error:', b)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print(f'[fail] see the log directory: {LOG}', flush=True)
        sys.exit(1)
