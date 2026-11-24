# Taiwan Affairs Office Press Conference Corpus

[English](README.md) | [简体中文](README.zh-CN.md)

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-stdlib--only-success)
![Tests](https://img.shields.io/badge/pytest-20%20passed-success)
![License](https://img.shields.io/badge/license-MIT%20(code)-blue)
![Corpus](https://img.shields.io/badge/corpus-441%20sessions%20%C2%B7%207%2C597%20QA-orange)

A clean, structured, searchable and reproducible local corpus of the **"Press Conference Transcripts"** (新闻发布会辑录) section of the Taiwan Affairs Office (TAO) website: one Markdown file per session, one raw HTML snapshot per session, machine-readable Q&A pairs, and a full-text-searchable SQLite database.

```bash
python scrape_gtb.py rebuild     # build everything offline from raw/ (no network)
python scrape_gtb.py search 九二共识 -n 3
```

> **Source:** <https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/>
> **Dataset:** Archived on Harvard Dataverse — DOI [10.7910/DVN/YHDWIJ](https://doi.org/10.7910/DVN/YHDWIJ).
> **Code:** MIT.
> **Corpus:** text copyright belongs to the Taiwan Affairs Office of the State Council. Provided for research and teaching only — **no commercial use, no resale, and no redistribution of the full text**. See [Copyright and license](#copyright-and-license).

**中文摘要**：本仓库把国台办官网「新闻发布会辑录」整理为干净、结构化、可检索、可复现的本地语料库：441 期发布会、7,597 组问答、逐期原始 HTML 快照，支持零网络重建与单字中文检索。完整中文文档见 [`README.zh-CN.md`](README.zh-CN.md)。

## What you get

| Output | Description |
|---|---|
| **441 sessions** | Full transcripts from 2000-09-05 to 2026-10-21; 2,895,276 characters including bold markers (2,842,158 characters after stripping markup and whitespace) |
| **7,597 Q&A pairs** | Journalist question → spokesperson answer, paired in order, with asker and speaker names |
| **Clean Markdown** | Page headers, navigation, scripts, editor credits, "report an error" links and sharing widgets removed |
| **Raw snapshots** | One original HTML fragment per session, so every derived artifact can be rebuilt offline |
| **Chinese full-text search** | SQLite FTS5 + trigram: even a single Chinese character can be searched, with no tokenizer or external service |
| **A reproducible pipeline** | Idempotent reruns, four-way consistency checks, 20 regression tests, zero lint warnings |

## Features

- 🪶 **Zero third-party dependencies** — standard library only (`urllib`, `re`, `sqlite3`, `hashlib`, `concurrent.futures`). Clone and run.
- 🔁 **Idempotent** — fetching the same pages again produces byte-identical output. A full refetch of 442 requests left all 1,323 file hashes unchanged.
- 📴 **Offline rebuild** — `raw/` is the authoritative source of the body text; `rebuild` regenerates Markdown, JSONL and SQLite without network access.
- 🔍 **Chinese-friendly search** — FTS5 `trigram` indexing matches arbitrary substrings; each hit is located by date + Q&A number + asker → speaker.
- 🧪 **Built-in health check** — `verify` compares Markdown ↔ JSONL ↔ database ↔ FTS and exits non-zero on problems, so it can run in CI.
- 🛡 **Atomic writes** — artifacts are written to `*.tmp` and then `os.replace`d; an interrupted run cannot leave half-written files.

## Repository contents

Shipped with the repository:

| Path | Size | Description |
|---|---|---|
| `data/YYYY-MM-DD.md` | 441 files / 8.7 MB | Finished transcripts, one file per session |
| `raw/YYYY-MM-DD.txt` | 441 files / 10.5 MB | Raw HTML snapshots used for offline rebuilds |
| `index.md` | 0.03 MB | Full index (date / paragraphs / characters / Q&A count) |
| `scrape_gtb.py` | single file | The entire CLI, standard library only |
| `tests/` | 7 files | 20 regression tests (`test_gtb.py`, `conftest.py`, 5 real-page fixtures) |
| `log/` | — | Historical run logs (examples) |
| `legacy/` | — | Archived v1 script and report; not used at runtime |

Generated locally and intentionally **not** committed:

| Path | Size | Command | Time |
|---|---|---|---|
| `data/jsonl/*.jsonl` | 8.7 MB | `rebuild` | a few seconds |
| `gtb.db` | 30.8 MB | `rebuild` | a few seconds |
| `gtb_qa.jsonl` | 8.5 MB | `rebuild` or `sync` | a few seconds |
| `gtb_all.md` | 8.5 MB | `export` | < 1 s |

These artifacts are excluded by `.gitignore`: they can be deterministically recomputed from `data/*.md` + `raw/`, so there is no reason to store 30 MB of binaries in Git.

## Quick start

**Requirements:** Python 3.9+ (tested on 3.9 and 3.12). No `pip install` is needed; `pytest` and `ruff` are only required for development.

```bash
cd gtb_scraper

# 1. Build derived artifacts (offline; reads raw/ and data/*.md)
python scrape_gtb.py rebuild

# 2. Self-check: Markdown ↔ JSONL ↔ database ↔ FTS
python scrape_gtb.py verify

# 3. Try a search
python scrape_gtb.py search 九二共识 -n 3

# 4. Optional: merge all 441 sessions into one file for LLM ingestion or sampling
python scrape_gtb.py export
```

CLI messages, help text, and status output are in English. Corpus content and
search results remain Chinese, as that is the source language.

Typical `rebuild` output:

```text
[rebuild] 441 issues (offline)
  441 issues generated (441 from raw/), 0 skipped, 7,597 Q&A pairs
```

Typical `verify` output:

```text
[verify] 441 issues · db 441 / 7,597 Q&A / fts 7,597
  note: 2 Q&A pairs have an empty question or answer (common in early press-release style)
  ✅ all checks passed
```

> **Note:** `verify`, `search` and `stats` need `gtb.db`. Running them before `rebuild` is expected to fail.
> Reading the transcripts does **not** require any build — `data/*.md` works out of the box.

## Data format

### Session Markdown (`data/2026-10-21.md`, excerpt)

```markdown
---
source: https://www.gwytb.gov.cn/.../t20261021_xxxx.htm
date: 2026-10-21
title: "国务院台办例行新闻发布会（2026-10-21）"
published: 2026-10-21 15:54
organization: 中共中央台办、国务院台办
paragraphs: 53
chars: 8521
qa: 22
sha: 3f9c1a2b7d4e5f60
---

# 国务院台办例行新闻发布会（2026-10-21）

> 发布：2026-10-21 15:54 来源：中共中央台办、国务院台办
> 原文：https://...

## 问答

**中央广播电视总台央视《海峡两岸》记者：**
Question text ...

**张晗：**
Answer text ...
```

- `sha`: first 16 hex characters of the SHA-256 of the body paragraphs; detects manual edits and divergence between rebuild paths.
- `chars`: character count of the body (including `**` bold markers). `paragraphs`: paragraph count. `qa`: number of Q&A pairs.
- Paragraphs that cannot be paired (opening remarks, additional notes) are kept under `## 其他段落` ("Other paragraphs") so no content is lost.

### Structured records (`data/jsonl/2026-10-21.jsonl`, one answer per line)

```json
{"date":"2026-10-21","seq":1,"asker":"中央广播电视总台央视《海峡两岸》记者","speaker":"张晗","question":"...","answer":"...","source":"https://...","title":"..."}
```

### Search results (`search 九二共识 -n 2`)

```text
[1] 2026-10-21 #5  《参考消息》记者 → 张晗
  问: 近期，有岛内民调显示，约六成台湾青年认为台湾不能依靠美国……
  答: 要和平、要发展、要交流、要合作是台湾社会主流民意……
```

The default output is human-readable. Add `--json` for a machine-readable array with the same fields as the JSONL records.

## Command reference

```text
python scrape_gtb.py <command> [options]
```

Human-readable CLI messages and help text are in English; corpus text and search results remain Chinese. Command names, options, exit codes, and `--json` output are language-neutral.

| Command | Purpose | Network |
|---|---|---|
| `sync` (default) | Incremental fetch → clean → write Markdown/JSONL/DB/index | ✅ |
| `rebuild` | Rebuild all Markdown/JSONL/DB/index from `raw/` + Markdown metadata | ❌ |
| `verify` | Whole-corpus consistency check; exit code 1 on problems | ❌ |
| `search` | Full-text search over Q&A pairs | ❌ |
| `stats` | Sessions / characters / Q&A / yearly distribution / top media and speakers | ❌ |
| `index` | Rebuild `index.md` | ❌ |
| `export` | Merge all session bodies into one Markdown file | ❌ |

With no subcommand, the CLI behaves like `sync`. `--version` prints the version; `--no-log` disables the log file.

### `sync` — incremental fetch

```bash
python scrape_gtb.py                       # same as sync
python scrape_gtb.py sync --limit 5        # only the 5 most recent sessions
python scrape_gtb.py sync --since 2024-01-01
python scrape_gtb.py sync --force          # ignore local cache and refetch everything
python scrape_gtb.py sync --workers 2      # concurrency (default 6)
python scrape_gtb.py sync --dry-run        # fetch and parse without writing
```

| Option | Default | Description |
|---|---|---|
| `--limit N` | all | Process only the N most recent sessions in the list |
| `--since YYYY-MM-DD` | empty | Process sessions on or after this date |
| `--force` | off | Ignore the "skip if sha unchanged" cache and refetch |
| `--workers N` | 6 | Concurrent detail-page requests |
| `--dry-run` | off | Fetch and parse, but do not write |

Each run ends with a summary of `new / updated / same / cached / failed`. A single failed session does not abort the run; details go to `log/`.

### `rebuild` — offline reconstruction

```bash
python scrape_gtb.py rebuild
python scrape_gtb.py rebuild --dry-run     # report only, write nothing
```

`raw/` is authoritative for body text and Markdown front matter is authoritative for metadata. `rebuild` regenerates Markdown, JSONL, the database and the index without network access, producing byte-identical results to the `sync` path (identical `sha`). This means the corpus can be reconstructed exactly on another machine, years later.

> `rebuild` **overwrites** the Markdown body from `raw/`. Manual edits to the body will be lost; edit `raw/` or the cleaning logic instead (and `verify` will first report `sha-mismatch`).

### `verify` — consistency check

```bash
python scrape_gtb.py verify
python scrape_gtb.py verify --fix   # use Markdown as truth to repair JSONL and DB
```

Checks include: `sha` / `chars` / `qa` consistency with front matter; residual HTML (`&nbsp;`, tags); noise (`****`, full-width spaces); suspiciously short bodies; JSONL line count and sequence continuity; database presence and matching `sha`/`qa`; FTS row count matching the `qa` table. A missing `raw/` file is only a warning (`rebuild` then falls back to Markdown).

### `search` — full-text search

```bash
python scrape_gtb.py search 九二共识           # 10 results by default
python scrape_gtb.py search 台商 -n 20
python scrape_gtb.py search "九二共识 台商"     # multiple words = AND (quote the whole string)
python scrape_gtb.py search 赖 -n 5 --json      # machine-readable output
```

| Option | Default | Description |
|---|---|---|
| `-n, --limit` | 10 | Number of results |
| `--json` | off | Output a JSON array |

- Multiple words separated by spaces are combined with **AND**. Pass the whole string as one argument (quoted); otherwise the shell splits it and the CLI errors.
- Queries of 3+ characters use the FTS5 index; 1–2 character queries automatically fall back to `LIKE '%term%'`, so **a single Chinese character is searchable**.
- Exit code is 1 when there are no results, which makes scripting easier.

### `stats` / `index` / `export`

```bash
python scrape_gtb.py stats                 # sessions, characters, Q&A, by year, top-10 media, top-10 speakers
python scrape_gtb.py index                 # rebuild index.md (date / paragraphs / characters / Q&A)
python scrape_gtb.py export                # generate gtb_all.md (all bodies merged)
python scrape_gtb.py export --out /tmp/all.md
```

Sample `stats` output (excerpt):

```text
Issues 441 · body 2,895,276 chars · Q&A 7,597 pairs

By year:
  2026   35 issues   796 Q&A   322,462 chars
  2025   29 issues   726 Q&A   295,536 chars
  ...
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | `sync` had a failed session / `verify` found problems / `search` found nothing / `rebuild` skipped sessions |
| `2` | Invalid arguments |
| `130` | Interrupted (Ctrl-C) |

## Data model

### Directory layout

```text
scrape_gtb.py                 Single-file CLI (standard library only)
data/YYYY-MM-DD.md            Finished transcript: front matter + title + Q&A / other paragraphs
data/jsonl/YYYY-MM-DD.jsonl   Structured Q&A (generated by rebuild)
raw/YYYY-MM-DD.txt            Raw HTML fragment (authoritative source for offline rebuild)
gtb.db                        SQLite: conference / qa / qa_fts (generated by rebuild)
gtb_all.md                    All bodies merged (generated by export)
gtb_qa.jsonl                  All Q&A merged (generated by sync / rebuild)
index.md                      Index table (date / paragraphs / characters / Q&A)
log/YYYYMMDD-HHMMSS-<cmd>.log Per-run log
tests/                        pytest cases + real-page fixtures
legacy/                       Archived v1, not used at runtime
```

### SQLite schema

```sql
conference(date PK, title, url, published, organization,
           paragraphs, chars, sha, qa_count, fetched_at, updated_at)
qa(id PK, date → conference.date, seq, asker, speaker, question, answer)
qa_fts   -- FTS5(external content = qa, tokenize='trigram')
```

FTS5 `external content` stores only the index, not a second copy of the text (database size drops from 55.6 MB to 30.8 MB).

Custom SQL query:

```sql
SELECT q.date, q.seq, q.speaker,
       snippet(qa_fts, 3, '【', '】', '…', 20) AS fragment
FROM qa_fts JOIN qa ON qa.id = qa_fts.rowid
WHERE qa_fts MATCH '九二共识'
ORDER BY q.date DESC LIMIT 5;
```

> The trigram tokenizer costs index space: 8.7 MB of Markdown becomes a 30.8 MB database (mostly the `qa` table and FTS index). In exchange, **no tokenization is required and arbitrary substrings are searchable**.

## Design decisions

| Decision | Rationale |
|---|---|
| **Single-file CLI, no module split** | At roughly one thousand lines, splitting adds navigation cost; one file carries all functionality |
| **Markdown is the product, raw is authoritative** | Humans read Markdown, machines read JSONL/DB; `raw/` guarantees the corpus can always be re-derived even if cleaning logic changes |
| **sha16 in front matter** | Makes "was this file edited?" and "are the two rebuild paths equivalent?" mechanically checkable, which is what `verify` relies on |
| **Derived artifacts are not committed** | Deterministic rebuild means no repository bloat; one command restores everything after clone |
| **Atomic writes** | Fetching 441 sessions is a long job; Ctrl-C must not leave a half-written Markdown file |
| **Failures are visible** | One failed session does not abort the run, but the exit code is non-zero and details go to the log, so sessions cannot silently disappear |
| **Concurrency 6, no throttling** | The site serves static pages and handles the load; use `--workers 1` to be more conservative. Only public pages are fetched; no access control is bypassed |

## Reliability

All figures below are actual runs of this project, not estimates:

| Check | Method | Result |
|---|---|---|
| Full-refetch idempotence | Refetch the whole site (442 requests) | `new 0 / updated 0 / same 441 / failed 0`; 1,323 file hashes unchanged |
| Two-path equivalence | Run `sync` and `rebuild` separately, in full | Converge to the same fixed point (byte-identical) |
| Four-way consistency | `verify` | 441 sessions · DB 441 · 7,597 Q&A · FTS 7,597; all passed |
| Build from scratch | New directory with only `scrape_gtb.py` + `data` + `raw` | Complete in ≈2–5 s; `verify` passes; search works |
| Tamper detection | Manually edit Markdown body | `verify` reports `sha-mismatch` (covered by a test) |
| Unit tests | `pytest` | 20 passed |
| Static checks | `ruff check .` | All checks passed |

## Development and testing

```bash
python -m pytest tests -q     # 20 tests, offline, fixtures are real page snapshots (original GBK bytes)
python -m ruff check .        # E/F/W/B/UP and related rules
```

Coverage includes: list-page parsing; two generations of detail templates (2000 legacy / 2011 / Q&A style / press-release style); noise cleaning; Q&A pairing; Markdown ↔ record round-trip; render idempotence; JSONL layout; empty front-matter values; sha stability; database overwrite and search; atomic writes; per-session idempotence; tamper detection; multi-word AND and short-query fallback.

Recommended loop after changing code:

```bash
python -m pytest tests -q && python -m ruff check . && python scrape_gtb.py verify
```

## FAQ

<details>
<summary><b>I just cloned the repo and search / stats / verify fail.</b></summary>

Run `python scrape_gtb.py rebuild` first to generate `gtb.db`. The database is not committed because it can be deterministically rebuilt and would add 30 MB of binary data.
</details>

<details>
<summary><b>Do I need to build anything just to read the transcripts?</b></summary>

No. `data/*.md` contains the complete transcripts and can be read by any Markdown editor or script.
</details>

<details>
<summary><b>Does rebuild use the network? Will it overwrite my edits?</b></summary>

It is fully offline and reads only local `raw/` and `data/*.md`. It **rewrites** the Markdown body from `raw/`, so manual edits to the body are overwritten (`verify` also reports `sha-mismatch` first). For permanent changes, edit `raw/` or the cleaning logic.
</details>

<details>
<summary><b>Why does one session have no Q&A (qa: 0)?</b></summary>

Only the earliest session, 2000-09-05, is a pure press release with no Q&A structure; its `qa` is 0 but the full body is preserved. Two Q&A pairs elsewhere have an empty question or answer; `verify` reports these as notes, not errors.
</details>

<details>
<summary><b>Why can search match a single Chinese character?</b></summary>

The FTS5 `trigram` tokenizer indexes 3-character windows, which supports arbitrary substrings; this project also adds a `LIKE` fallback for 1–2 character queries.
</details>

<details>
<summary><b>Will other people's scraping overload the site?</b></summary>

Defaults are 6 concurrent requests, at most 3 retries (backoff 1.5 s / 3 s / 4.5 s) and a 30 s timeout. To be conservative, use `--workers 1` and avoid frequent full `--force` refetches.
</details>

<details>
<summary><b>Can I change the data source or add another section?</b></summary>

See [Adaptation and extension](#adaptation-and-extension).
</details>

## Known limitations

- **One early session has no Q&A structure**: only 2000-09-05 is a pure press release (`qa` = 0); the body is fully preserved.
- **A site redesign will break the parser**: parsing depends on GBK static pages and two generations of DOM templates. A JSON API or client-side rendering would require changes to `collect_index()` / `parse_article()`.
- **Single section**: only "Press Conference Transcripts" is covered; statements, Q&A outside regular briefings, and special topics are not included.
- **No entity normalization**: the same speaker may carry a job-title prefix in different years and is not merged; no simplified/traditional conversion or named-entity recognition.
- **No append-only history**: the database overwrites a whole session on each run (for idempotence); historical versions are not retained.
- **Platform**: tested on macOS with Python 3.9 and 3.12. The code uses only the standard library and `os.replace`, so it should be portable, but **Windows/Linux are untested**.

## Adaptation and extension

| Need | Where to change |
|---|---|
| Site domain / section | `BASE` constant |
| List-page structure | `collect_index()` (pagination pattern `index.htm` / `index_N.htm`, 50 items per page) |
| Detail-page template | `parse_article()` + `paragraphs()` (two generations: `div.TRS_Editor` / `div#contentArea`) |
| New noise rule | `polish()` and `HTML_LEAK_RE` |
| Q&A pairing rule | `split_blocks()` / `classify()` / `extract_qa()` |
| New output format | Add a serializer after `build_record()`, write it in `save_record()` |
| Different database / new field | `db_connect()` schema + `db_upsert()` + matching check in `verify()` |

After changes, run `pytest` → `ruff` → `rebuild` → `verify`; commit only when all four pass.

## Copyright and license

- **Code**: MIT, see [`LICENSE`](LICENSE).
- **Corpus**: text copyright belongs to the **Taiwan Affairs Office of the State Council** (<https://www.gwytb.gov.cn>). This repository performs format conversion and structural organization for research, teaching and text analysis only:

  > **No commercial use. No resale. Do not republish the full text in the form of this repository.**
  > When citing, credit the original source and link to the original page.

- Fetching respects the site's publicly accessible pages and bypasses no access control or authentication.

Suggested academic citation:

```text
国务院台湾事务办公室. 新闻发布会文字实录（2000-09-05 至 2026-10-21）[DB/OL].
https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/（经 gtb_scraper 转换整理）
```

English translation:

```text
Taiwan Affairs Office of the State Council. Press Conference Transcripts
(2000-09-05 – 2026-10-21) [DB/OL]. https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/
(converted and organized with gtb_scraper)
```

Dataset citation (archived on Harvard Dataverse):

```text
Bin Liang, 2026, "Taiwan Affairs Office (TAO) Press Conference Transcript Corpus: 441 Sessions and 7,597 Q&A Pairs (2000-2026)", https://doi.org/10.7910/DVN/YHDWIJ, Harvard Dataverse, V1
```

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for the complete version history (including fixes and improvements). The table below summarizes the v1 → v2 upgrade; all figures are measured.

| Dimension | v1 (2026-10-20, first release) | v2 (this project) |
|---|---|---|
| Shape | One-shot scraping script | Single-file multi-command CLI: `sync / rebuild / index / verify / stats / search / export` |
| Outputs | `data/*.md` + `report.json` only | Markdown + **JSONL Q&A** + **SQLite (FTS5 trigram Chinese search)** + merged export + `index.md` |
| Full-text search | None (only `grep`) | `search keyword`: works from one character; hits located by session + Q&A number + asker/speaker |
| Offline rebuild | None (network required) | `rebuild`: `raw/` is authoritative; **zero-network** rebuild of all artifacts |
| Idempotence | Undefined | Body sha16 fingerprint + structured output; **reruns produce zero changes** (1,323 file hashes identical after 442 requests) |
| Incremental fetch | Full fetch every time | Date/cache skipping with `--since` / `--limit` / `--force` |
| Data consistency | No checks | `verify`: Markdown ↔ JSONL ↔ DB ↔ FTS comparison, non-zero exit code, `--fix` repairs derived files |
| Quality assurance | No tests | **20 pytest tests** (real-page fixtures: two template generations / Q&A / legacy) + zero `ruff` warnings |
| Error handling | Print failures | One failure does not abort the run; details in `log/`; final `new/updated/same/cached/failed` summary |
| Write safety | Direct overwrite | Atomic writes (`.tmp` + `os.replace`); interruption leaves no partial files |
| Documentation | One README paragraph | README (format contract / extension guide) + CHANGELOG + LICENSE (MIT code / corpus copyright) + pytest.ini + ruff.toml |
| Size | — | FTS5 external-content optimization: DB 55.6 MB → **30.8 MB** |
