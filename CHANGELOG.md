# Changelog

English | [简体中文](README.zh-CN.md)

## v2.1 (2026-11-24)

English-first code and documentation. Data formats are unchanged; existing corpus files remain compatible.

### Added

- All CLI help, status, error messages, comments, and docstrings are now in English.
- Full Chinese README ([README.zh-CN.md](README.zh-CN.md)) and a bilingual changelog.
- Python 3.9 support: removed `zip(strict=True)` where the inputs are known to be equal-length.

### Changed

- Generated `index.md` headings and the merged `export` title are English; corpus content remains Chinese.
- Search/statistics/verify output labels are English, while matching and stored text stay Chinese.

## v2 (2026-10-24)

Structured rewrite. Data remains compatible with v1: Markdown bodies are unchanged; only metadata parsing was corrected.

### Added

- Single-file CLI with subcommands: `sync` / `rebuild` / `index` / `verify` / `stats` / `search` / `export`.
- Structured Q&A pairs in `data/jsonl/YYYY-MM-DD.jsonl` (one pair per line).
- Multi-term AND search (space-separated; quote the whole query) and automatic LIKE fallback for 1–2 character terms.
- SQLite database `gtb.db` with `conference`, `qa`, and `qa_fts` (FTS5 trigram; single-character Chinese lookup supported).
- Offline `rebuild` from `raw/` HTML as the authoritative body source — no network needed to regenerate all products.
- `verify`: four-way consistency (md ↔ jsonl ↔ db ↔ fts) plus SHA checks; `--fix` repairs derived files.
- Per-session `sha` (first 16 hex chars of the body SHA-256), `chars`, `paragraphs`, and `qa` statistics.
- 20 pytest regression tests, including search semantics (multi-term AND / short-term LIKE fallback). Fixtures are real page snapshots and run offline.
- Atomic writes (`tmp` + `os.replace`), run logs, and documented exit codes.

### Fixed

- Front-matter parsing: `\s*` consumed newlines, so an empty field such as `organization:` swallowed the next line into its value. Changed to `[ \t]*` (same bug in `_frontmatter` and `md_to_record`).
- `db_connect()` bound the DB path as a default argument at definition time, so tests or path overrides connected to the wrong database. Now resolved at call time.

### Improved

- FTS5 switched to external content (`content='qa'`) to avoid storing the body twice: DB 55.6 MB → 30.8 MB.
- Top-level `-h` now shows subcommand help (previously treated as a `sync` argument).
- Corrected the `sync --dry-run` help text to “fetch and parse but do not write” (the old “fetch only” wording was misleading).

## v1 (2026-10-20)

Initial release: a single scraping script with cleaning, one Markdown file per session, `index.md`, and logs under `log/`.

---

# 变更记录（中文）

## v2.1（2026-11-24）

代码与文档改为英文优先。数据格式不变，已有语料保持兼容。

### 新增

- CLI 帮助、状态/错误消息、注释和 docstring 全部改为英文。
- 完整中文 README（[README.zh-CN.md](README.zh-CN.md)）与中英双语变更记录。
- 支持 Python 3.9：在输入等长的位置移除 `zip(strict=True)`。

### 变更

- 生成的 `index.md` 标题和 `export` 合并标题改为英文；语料正文仍为中文。
- 检索/统计/校验的输出标签改为英文，匹配与存储的文本仍为中文。

## v2（2026-10-24）

结构化改造，数据与 v1 保持兼容（md 内容不变，仅元数据解析修正）。

### 新增

- 单文件 CLI 多子命令：`sync` / `rebuild` / `index` / `verify` / `stats` / `search` / `export`
- 结构化问答对 `data/jsonl/YYYY-MM-DD.jsonl`（每行一组问答）
- 检索支持多词 AND（空格分隔，须整串加引号传递）、1–2 字自动退化 LIKE
- SQLite 库 `gtb.db`：`conference` + `qa` + `qa_fts`（FTS5 trigram，支持 1 字中文检索）
- 离线重建 `rebuild`：以 `raw/` 原始 HTML 为正文权威，不联网重算全部产物
- `verify`：md ↔ jsonl ↔ db ↔ fts 四向一致 + sha 校验，`--fix` 可修复派生文件
- `sha` 字段（正文段落 sha256 前 16 位）与 `chars` / `paragraphs` / `qa` 统计
- pytest 回归测试 20 项：含检索语义（多词 AND / 短词 LIKE 回退），fixtures 为真实页面快照，离线运行
- 原子写入（tmp + os.replace）、运行日志、退出码规范

### 修复

- front matter 解析中 `\s*` 会吞掉换行，导致空值字段（如 `organization:`）把下一行吃进取值 → 改为 `[ \t]*`（`_frontmatter` 与 `md_to_record` 两处同源 bug）
- `db_connect()` 默认参数在定义期绑定 DB 路径，导致测试/改路径时连错库 → 改为运行时解析

### 优化

- FTS5 改为 external content（`content='qa'`），避免正文二次存储：db 55.6 MB → 30.8 MB
- 顶层 `-h` 正确显示子命令帮助（此前会被当作 `sync` 参数）
- `sync --dry-run` 帮助文案修正为「抓取并解析但不写盘」（原「只抓不算」易误解）

## v1（2026-10-20）

初版：单脚本抓取 + 清洗 + 一期一 md + index.md + 日志入 log/。
