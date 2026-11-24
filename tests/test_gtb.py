"""gtb_scraper regression tests: parsing, cleaning, Q&A segmentation,
serialization, storage, and idempotency.

Fully offline: fixtures are real page snapshots (GBK); no network requests.
"""
import hashlib
import json
import os

import pytest

import scrape_gtb as g

DATE = '2026-10-21'


def _rec(load_fixture, name='new_2026-10-21.htm', date=DATE, url='https://x/y.htm'):
    h = load_fixture(name)
    title, info, body = g.parse_article(h)
    paras = g.polish(g.paragraphs(body), title)
    return g.build_record({'date': date, 'url': url, 'title': title}, title, info, paras)


# ---------------------------------------------------------------- Listing page
def test_list_page_items(load_fixture):
    h = load_fixture('list.htm')
    found = g.ITEM_RE.findall(h)
    assert len(found) == 50
    dates = [f[0] for f in found]
    assert dates == sorted(dates, reverse=True)
    assert all(f[1].startswith(('http', '/')) for f in found)


# ---------------------------------------------------------------- Article page
@pytest.mark.parametrize('fixture,has_qa', [
    ('new_2026-10-21.htm', True),
    ('qa_2021-11-24.htm', True),
    ('old_2011-11-16.htm', True),
    ('news_2000-09-05.htm', False),
])
def test_parse_article_shapes(load_fixture, fixture, has_qa):
    title, info, body = g.parse_article(load_fixture(fixture))
    assert title and '发布会' in title
    assert body and ('TRS_Editor' in body[:80] or 'contentArea' in body[:80])
    assert '<script' not in body.lower()              # header/navigation scripts removed


def test_published_and_org_parsed(load_fixture):
    _, info, _ = g.parse_article(load_fixture('new_2026-10-21.htm'))
    pub, org = g.parse_info(info)
    assert pub == '2026-10-21 15:54'
    assert org == '中共中央台办、国务院台办'


# ---------------------------------------------------------------- Cleaning
def test_polish_removes_navigation_noise(load_fixture):
    title, _, body = g.parse_article(load_fixture('new_2026-10-21.htm'))
    paras = g.polish(g.paragraphs(body), title)
    assert len(paras) > 30
    for p in paras:
        assert p.strip()
        assert not p.startswith('>')
        assert '来源：' not in p[:12]
        assert p.strip('*') != title            # title no longer leaks into the body
        assert '**' not in p.replace('**', '', 0) or p.count('**') % 2 == 0


# ---------------------------------------------------------------- Q&A segmentation
def test_two_bold_speaker_styles():
    for p in ('**朱凤莲：**大家上午好', '**朱凤莲**：大家上午好'):
        m = g.BOLD_SPEAKER_RE.match(p)
        assert m and m.group('name') == '朱凤莲'
        assert m.group('text').startswith('大家上午好')


def test_extract_qa_structure(load_fixture):
    rec = _rec(load_fixture, 'qa_2021-11-24.htm', '2021-11-24')
    qa = rec['qa']
    assert len(qa) >= 10
    assert [q['seq'] for q in qa] == list(range(1, len(qa) + 1))
    assert all(q['asker'] for q in qa)
    assert all(q['speaker'] == '朱凤莲' for q in qa)
    assert sum(1 for q in qa if q['answer']) == len(qa)
    assert rec['opening']                      # opening remarks present


def test_extract_qa_news_style(load_fixture):
    rec = _rec(load_fixture, 'news_2000-09-05.htm', '2000-09-05')
    assert rec['qa'] == []                     # early press-release style: no Q&A structure
    assert rec['paragraphs'] >= 5


# ---------------------------------------------------------------- Serialization
def test_md_roundtrip_is_lossless(load_fixture):
    rec = _rec(load_fixture)
    text = g.record_to_md(rec)
    back = g.md_to_record(text, DATE)
    assert back['title'] == rec['title']
    assert back['published'] == rec['published']
    assert back['organization'] == rec['organization']
    assert back['paragraphs'] == rec['paragraphs']
    assert back['chars'] == rec['chars']
    assert back['sha'] == rec['sha']
    assert back['qa'] == rec['qa']
    assert back['body'] == rec['body']


def test_md_render_idempotent(load_fixture):
    rec = _rec(load_fixture)
    once = g.record_to_md(rec)
    twice = g.record_to_md(g.md_to_record(once, DATE))
    assert once == twice


def test_jsonl_layout(load_fixture):
    rec = _rec(load_fixture)
    lines = [json.loads(x) for x in g.record_to_jsonl(rec).splitlines()]
    assert lines[0]['type'] == 'conference'
    assert lines[0]['date'] == DATE
    assert len(lines) == 1 + len(rec['qa'])
    for i, obj in enumerate(lines[1:], 1):
        assert obj['type'] == 'qa' and obj['seq'] == i
        assert set(obj) == {'type', 'date', 'seq', 'asker', 'speaker', 'question', 'answer'}


def test_frontmatter_empty_value_does_not_eat_next_line():
    fm = g._frontmatter('---\ndate: 2000-09-05\norganization: \nparagraphs: 9\n---\n正文')
    assert fm['organization'] == ''
    assert fm['paragraphs'] == '9'


def test_sha16_stable():
    assert g.sha16('两岸一家亲') == g.sha16('两岸一家亲')
    assert len(g.sha16('x')) == 16
    assert g.sha16('a') != g.sha16('b')


# ---------------------------------------------------------------- Storage
def test_db_upsert_idempotent_and_search(load_fixture, tmp_path):
    rec = _rec(load_fixture)
    db = str(tmp_path / 't.db')
    conn = g.db_connect(db)
    for _ in range(2):                        # repeated upserts must not duplicate rows
        g.db_upsert(conn, rec)
        conn.commit()
    n_conf, n_qa = conn.execute('SELECT (SELECT COUNT(*) FROM conference), '
                                '(SELECT COUNT(*) FROM qa)').fetchone()
    n_fts = conn.execute('SELECT COUNT(*) FROM qa_fts').fetchone()[0]
    assert (n_conf, n_qa, n_fts) == (1, len(rec['qa']), len(rec['qa']))

    assert g.db_search(conn, '两岸经贸', 3)          # >=3 chars -> FTS MATCH
    assert g.db_search(conn, '台商', 3)              # 2 chars -> LIKE fallback
    assert g.db_search(conn, '绝无此词xyzzy', 3) == []
    conn.close()


def test_atomic_write_no_temp_leftover(tmp_path):
    p = tmp_path / 'a' / 'b.txt'
    g.atomic_write(str(p), '内容')
    assert p.read_text(encoding='utf-8') == '内容'
    assert list(os.listdir(tmp_path / 'a')) == ['b.txt']


# ---------------------------------------------------------------- End-to-end: idempotency
def test_process_one_is_idempotent(load_fixture, tmp_path, monkeypatch):
    html = load_fixture('new_2026-10-21.htm')
    data, raw = tmp_path / 'data', tmp_path / 'raw'
    monkeypatch.setattr(g, 'DATA', str(data))
    monkeypatch.setattr(g, 'JSONL', str(data / 'jsonl'))
    monkeypatch.setattr(g, 'RAW', str(raw))
    monkeypatch.setattr(g, 'get_text', lambda url: html)

    item = {'date': DATE, 'url': 'https://x/y.htm', 'title': 't'}
    r1 = g.process_one(item, force=True)
    md1 = (data / f'{DATE}.md').read_bytes()
    rawhash = hashlib.sha256((raw / f'{DATE}.txt').read_bytes()).hexdigest()
    r2 = g.process_one(item, force=True)

    assert r1['status'] == 'new'
    assert r2['status'] == 'same'
    assert (data / f'{DATE}.md').read_bytes() == md1
    assert hashlib.sha256((raw / f'{DATE}.txt').read_bytes()).hexdigest() == rawhash
    assert r2['rec']['qa'] == r1['rec']['qa']


def test_verify_detects_tampering(load_fixture, tmp_path, monkeypatch):
    data = tmp_path / 'data'
    monkeypatch.setattr(g, 'DATA', str(data))
    monkeypatch.setattr(g, 'JSONL', str(data / 'jsonl'))
    monkeypatch.setattr(g, 'RAW', str(tmp_path / 'raw'))
    monkeypatch.setattr(g, 'DB', str(tmp_path / 'v.db'))
    monkeypatch.setattr(g, 'INDEX_MD', str(tmp_path / 'index.md'))
    monkeypatch.setattr(g, 'MERGED', str(tmp_path / 'm.jsonl'))

    rec = _rec(load_fixture)
    g.save_record(rec)
    conn = g.db_connect(str(tmp_path / 'v.db'))
    g.db_upsert(conn, rec)
    conn.commit()
    conn.close()
    assert g.verify() == 0                    # clean corpus

    p = data / f'{DATE}.md'
    p.write_text(p.read_text(encoding='utf-8').replace('国务院', '国务院x'),
                 encoding='utf-8')
    assert g.verify() > 0                     # body tampered -> must report an error

def test_search_multi_term_is_and(tmp_path, load_fixture):
    rec = _rec(load_fixture)
    rec['qa'] = [
        {'seq': 1, 'asker': '记者甲', 'speaker': '发言人甲',
         'question': '台商权益保护有哪些举措', 'answer': '甲答'},
        {'seq': 2, 'asker': '记者乙', 'speaker': '发言人乙',
         'question': '九二共识的历史意义', 'answer': '乙答'},
    ]
    conn = g.db_connect(str(tmp_path / 's.db'))
    g.db_upsert(conn, rec)
    conn.commit()

    assert [r['seq'] for r in g.db_search(conn, '台商 权益')] == [1]
    assert g.db_search(conn, '九二 台商') == []        # terms in different pairs -> AND misses
    assert [r['seq'] for r in g.db_search(conn, '九')] == [2]   # single char -> LIKE fallback
    conn.close()
