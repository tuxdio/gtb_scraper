# 国务院台办新闻发布会文字实录语料库

[English](README.md) | **简体中文**

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![依赖](https://img.shields.io/badge/dependencies-stdlib--only-success)
![测试](https://img.shields.io/badge/pytest-20%20passed-success)
![许可](https://img.shields.io/badge/license-MIT%20(code)-blue)
![语料](https://img.shields.io/badge/corpus-441%20sessions%20%C2%B7%207%2C597%20QA-orange)

把国台办官网「新闻发布会辑录」栏目整理成**干净、结构化、可检索、可复现**的本地语料库：
一期一个 Markdown、一期一份原始 HTML 快照、一组问答对、一个可全文检索的 SQLite 库。

```bash
python scrape_gtb.py rebuild     # 从 raw/ 离线构建（不联网，约 2 秒）
python scrape_gtb.py search 九二共识 -n 3
```

> 数据来源：<https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/> ｜ 数据存档：Harvard Dataverse，DOI [10.7910/DVN/YHDWIJ](https://doi.org/10.7910/DVN/YHDWIJ) ｜ 代码 MIT ｜ 语料版权归国务院台办，**仅供研究/教学，禁止商用转售**（详见[版权与许可](#版权与许可)）

## 这是什么

| 你得到的 | 说明 |
|---|---|
| **441 期**发布会全文 | 2000-09-05 ~ 2026-10-21，共 2,895,276 字 |
| **7,597 组问答对** | 「记者提问 → 发言人回答」按顺序配对，带提问方与发言人名 |
| 干净的 Markdown | 去页头、导航、脚本、编辑署名、「【纠错】」「分享到」等噪声 |
| 原始快照 `raw/` | 每期原始 HTML 片段，保证任何派生产物都能离线重算 |
| 中文全文检索 | SQLite FTS5 + trigram，**1 个字也能查**，无需分词、无需外部服务 |
| 可复现的工程 | 幂等重跑、四方一致性校验、20 项回归测试、静态检查零告警 |

## 特性

- 🪶 **零第三方依赖** —— 只用标准库（`urllib` / `re` / `sqlite3` / `hashlib` / `concurrent.futures`），`git clone` 即可运行
- 🔁 **幂等** —— 同一份网页重复抓取，产物字节级一致；已实测 442 次请求全量重抓后 1,323 个文件哈希零变化
- 📴 **离线可重建** —— `raw/` 是正文权威，`rebuild` 不联网即可重算 md / jsonl / db
- 🔍 **中文检索友好** —— FTS5 `trigram` 分词，任意长度子串命中，命中定位到「日期 + 问答序号 + 提问方 → 发言人」
- 🧪 **自带体检** —— `verify` 做 md ↔ jsonl ↔ db ↔ FTS 四方比对，异常退出码非 0，可直接进 CI
- 🛡 **写盘原子** —— 所有产物先写 `*.tmp` 再 `os.replace`，中断不会留下半截文件

## 目录

- [快速开始](#快速开始) —— 三步构建、第一条查询
- [仓库内容](#仓库内容) —— 有什么、没有什么、各文件多大
- [数据长什么样](#数据长什么样) —— md / jsonl / 检索结果的真实样例
- [命令参考](#命令参考) —— 7 个子命令与全部参数
- [数据模型](#数据模型) —— 目录结构、front matter、SQLite 表与 FTS
- [设计取舍](#设计取舍) —— 为什么这样设计，边界在哪
- [可靠性验证](#可靠性验证) —— 实测记录
- [开发与测试](#开发与测试)
- [常见问题](#常见问题)
- [已知局限](#已知局限)
- [适配与扩展](#适配与扩展)
- [版权与许可](#版权与许可)
- [变更记录](#变更记录)

## 快速开始

**前提**：Python 3.9+（实测 3.9 与 3.12）。不需要 `pip install` 任何东西。
跑测试才需要 `pytest`、`ruff`（可选）。

```bash
cd gtb_scraper

# ① 构建派生产物（离线，读 raw/ 与 data/*.md）
python scrape_gtb.py rebuild

# ② 自检：md ↔ jsonl ↔ db ↔ FTS 四方一致
python scrape_gtb.py verify

# ③ 试一条检索
python scrape_gtb.py search 九二共识 -n 3

# ④ 可选：把 441 期正文合并成单文件，便于整库投喂模型 / 全文抽样
python scrape_gtb.py export
```

`rebuild` 的实测输出：

```text
[rebuild] 441 issues (offline)
  441 issues generated (441 from raw/), 0 skipped, 7,597 Q&A pairs
```

`verify` 的实测输出：

```text
[verify] 441 issues · db 441 / 7,597 Q&A / fts 7,597
  note: 2 Q&A pairs have an empty question or answer (common in early press-release style)
  ✅ all checks passed
```

> **注意**：`verify` / `search` / `stats` 依赖 `gtb.db`，未 `rebuild` 前运行会报错，属预期。
> 只是读正文的话**不需要任何构建** —— `data/*.md` 开箱即用。

## 仓库内容

| 有（随仓库分发） | 体量 | 说明 |
|---|---|---|
| `data/YYYY-MM-DD.md` | 441 个 / 8.7 MB | 成品正文，一期一文件 |
| `raw/YYYY-MM-DD.txt` | 441 个 / 10.5 MB | 原始 HTML 快照，离线重建的依据 |
| `index.md` | 0.03 MB | 全量索引（日期 / 段落 / 字数 / 问答数） |
| `scrape_gtb.py` | 1,043 行 | 全部功能（单文件 CLI） |
| `tests/` | 7 文件 | 20 项回归测试（`test_gtb.py` + `conftest.py` + 5 个真实页面快照） |
| `log/` | — | 历史运行日志（示例参考） |
| `legacy/` | — | v1 存档脚本与旧报告，不参与运行 |

| 没有（本地生成，可选） | 体积 | 生成命令 | 耗时 |
|---|---|---|---|
| `data/jsonl/*.jsonl` | 8.7 MB | `rebuild` | ≈2 s |
| `gtb.db` | 30.8 MB | `rebuild` | ≈2 s |
| `gtb_qa.jsonl` | 8.5 MB | `rebuild`（或 `sync`） | ≈2 s |
| `gtb_all.md` | 8.5 MB | `export` | ≈0.2 s |

派生产物已在 `.gitignore` 中排除 —— 它们能由仓库内的 md + raw **确定性重算**，无需占用版本库体积。

## 数据长什么样

### 一期 Markdown（`data/2026-10-21.md`，节选）

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
问题文本……

**张晗：**
回答文本……
```

- `sha`：正文段落 sha256 前 16 位，用来发现「文件被改动」或「两条重建路径不一致」
- `chars`：正文（含 `**` 加粗标记）字符数；`paragraphs`：段落数；`qa`：问答组数
- 无法配对的段落（开场白、补充说明等）放在 `## 其他段落`，不丢内容

### 结构化记录（`data/jsonl/2026-10-21.jsonl`，每行一答）

```json
{"date":"2026-10-21","seq":1,"asker":"中央广播电视总台央视《海峡两岸》记者","speaker":"张晗","question":"……","answer":"……","source":"https://…","title":"…"}
```

### 检索结果（`search 九二共识 -n 2`）

```text
[1] 2026-10-21 #5  《参考消息》记者 → 张晗
  问: 近期，有岛内民调显示，约六成台湾青年认为台湾不能依靠美国……
  答: 要和平、要发展、要交流、要合作是台湾社会主流民意……
```

默认输出人类可读格式；加 `--json` 得到机读数组（字段同 jsonl）。

## 命令参考

```text
python scrape_gtb.py <命令> [参数]
```

| 命令 | 作用 | 联网 |
|---|---|---|
| `sync`（默认） | 增量抓取 → 清洗 → 写 md/jsonl/db/index | ✅ |
| `rebuild` | 用 `raw/` + md 元数据重建全部 md/jsonl/db/index | ❌ |
| `verify` | 全库一致性校验，异常退出码 1 | ❌ |
| `search` | 全文检索问答 | ❌ |
| `stats` | 期数 / 字数 / 问答数 / 按年分布 / Top 媒体与发言人 | ❌ |
| `index` | 重建 `index.md` | ❌ |
| `export` | 把全部期正文合并成单个 markdown | ❌ |

不带子命令时等价于 `sync`；`--version` 看版本；`--no-log` 关掉日志文件。

### sync —— 增量抓取

```bash
python scrape_gtb.py                       # = sync
python scrape_gtb.py sync --limit 5        # 只处理最近 5 期（快速验证）
python scrape_gtb.py sync --since 2024-01-01
python scrape_gtb.py sync --force          # 忽略本地缓存，全部重新下载比对
python scrape_gtb.py sync --workers 2      # 并发数（默认 6）
python scrape_gtb.py sync --dry-run        # 抓取并解析但不写盘，预览变更
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--limit N` | 全部 | 只处理列表最近的 N 期 |
| `--since YYYY-MM-DD` | 空 | 只处理该日期及之后 |
| `--force` | 关 | 忽略「sha 未变则跳过缓存」的优化，强制下载 |
| `--workers N` | 6 | 详情页并发数 |
| `--dry-run` | 关 | 只抓取解析、不写盘 |

结束会打印 `new / updated / same / cached / 失败` 汇总；单期失败不影响整体，明细在 `log/`。

### rebuild —— 离线重建

```bash
python scrape_gtb.py rebuild
python scrape_gtb.py rebuild --dry-run     # 只统计不写盘
```

以 `raw/` 为正文权威、md 的 front matter 为元数据来源，重算 md / jsonl / db / index。
结果与 `sync` 路径逐字节一致（`sha` 相同），因此**换电脑、换机器、数年后都可精确复原**。

### verify —— 一致性校验

```bash
python scrape_gtb.py verify
python scrape_gtb.py verify --fix   # 以 md 为准，反向修补 jsonl 与 db
```

检查项：`sha` / `chars` / `qa` 数是否与 front matter 一致、HTML 残留（`&nbsp;`、标签）、
噪声（`****`、全角空格）、过短正文、jsonl 行数与序号连续性、db 中是否存在且 sha/qa 数匹配、
FTS 行数是否与 qa 表一致；`raw/` 缺失只作提示（rebuild 则退化为仅用 md）。

### search —— 全文检索

```bash
python scrape_gtb.py search 九二共识           # 默认 10 条
python scrape_gtb.py search 台商 -n 20
python scrape_gtb.py search "九二共识 台商"     # 多词 = AND（整串要加引号）
python scrape_gtb.py search 赖 -n 5 --json      # 机读输出
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `-n, --limit` | 10 | 返回条数 |
| `--json` | 关 | 输出 JSON 数组 |

- 多词用空格分隔，语义为 **AND**；整串必须作为一个参数传入（加引号），否则被 shell 拆分报错
- ≥3 字走 FTS5 索引；1–2 字自动退化为 `LIKE '%词%'`，**中文 1 个字也能查**
- 无结果时退出码为 1，便于脚本判断

### stats / index / export

```bash
python scrape_gtb.py stats                 # 期数、字数、问答数、按年、Top10 媒体、Top10 发言人
python scrape_gtb.py index                 # 重建 index.md（日期 / 段落 / 字数 / 问答）
python scrape_gtb.py export                # 生成 gtb_all.md（全部正文合并）
python scrape_gtb.py export --out /tmp/all.md
```

`stats` 实测输出（节选）：

```text
Issues 441 · body 2,895,276 chars · Q&A 7,597 pairs

By year:
  2026   35 issues   796 Q&A   322,462 chars
  2025   29 issues   726 Q&A   295,536 chars
  ...
```

### 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | `sync` 有单期失败 / `verify` 发现问题 / `search` 无结果 / `rebuild` 有跳过 |
| `2` | 参数错误 |
| `130` | 手动中断（Ctrl-C） |

## 数据模型

### 目录结构

```text
scrape_gtb.py                 单文件 CLI（仅标准库）
data/YYYY-MM-DD.md            成品正文：front matter + 标题 + 问答 / 其他段落
data/jsonl/YYYY-MM-DD.jsonl   结构化问答（rebuild 生成）
raw/YYYY-MM-DD.txt            原始 HTML 片段（离线重建权威源）
gtb.db                        SQLite：conference / qa / qa_fts（rebuild 生成）
gtb_all.md, gtb_qa.jsonl      合并导出（export 生成）
index.md                      索引表（日期 / 段落 / 字数 / 问答）
log/YYYYMMDD-HHMMSS-<cmd>.log 每次运行日志（tee 到文件）
tests/                        pytest 用例 + 真实页面快照
legacy/                       v1 存档，不参与运行
```

### SQLite

```sql
conference(date PK, title, url, published, organization,
           paragraphs, chars, sha, qa_count, fetched_at, updated_at)
qa(id PK, date → conference.date, seq, asker, speaker, question, answer)
qa_fts   -- FTS5(external content = qa, tokenize='trigram')
```

`external content` 让 FTS 只存索引不重复存正文（db 从 55.6 MB 降到 30.8 MB）。

自定义 SQL 查询：

```sql
SELECT q.date, q.seq, q.speaker,
       snippet(qa_fts, 3, '【', '】', '…', 20) AS 片段
FROM qa_fts JOIN qa ON qa.id = qa_fts.rowid
WHERE qa_fts MATCH '九二共识'
ORDER BY q.date DESC LIMIT 5;
```

> trigram 的代价是索引体积：本库 441 期正文 8.7 MB，`gtb.db` 达 30.8 MB（qa 表 + FTS 索引为主）。
> 换来的是**不需要分词、任意长度子串可查**。

## 设计取舍

| 决策 | 理由 |
|---|---|
| **单文件 CLI，不拆分模块** | 项目体量（1 千行）拆分反而增加跳转成本；复制一个文件即可带走全部能力 |
| **md 是成品，raw 是权威** | 人读 md、机器读 jsonl/db；raw 保证任何时候都能重新推导，避免「清洗逻辑一改，旧数据无法追溯」 |
| **sha16 写进 front matter** | 让「文件是否被改动」「两条重建路径是否等价」可被机械判定，`verify` 才有依据 |
| **派生产物不入库** | 可确定性重建 → 不占版本库；clone 后一条命令复原 |
| **原子写** | 抓 441 期是长任务，中途 Ctrl-C 不能留下半截 md |
| **失败可见** | 单期失败不中断全局，但退出码非 0 且明细进日志，避免「悄悄少了几期」 |
| **并发 6，不做节流** | 站点为静态页、负载可承受；如需更保守用 `--workers 1`。抓取只走公开页面，未绕过任何访问控制 |

## 可靠性验证

以下均为本项目实际执行记录（非估算）：

| 验证 | 方法 | 结果 |
|---|---|---|
| 全量重抓幂等 | 442 次请求重跑全站 | `new 0 / updated 0 / same 441 / 失败 0`，1,323 个文件哈希零变化 |
| 双路径一致 | `sync` 与 `rebuild` 各自全量执行 | 收敛到同一不动点（字节一致） |
| 四方一致性 | `verify` | 441 issues · db 441 · 7,597 Q&A · fts 7,597，全部通过 |
| 从零构建 | 仅 `scrape_gtb.py + data + raw` 的新目录 | 2.2 s 生成齐全，`verify` 通过，检索可用 |
| 篡改检测 | 手工改动 md 正文 | `verify` 报 `sha-mismatch`（已固化为测试） |
| 单元测试 | `pytest` | 20 passed |
| 静态检查 | `ruff check .` | All checks passed |

## 开发与测试

```bash
python -m pytest tests -q     # 20 项，离线，夹具为真实页面快照（GBK 原始字节）
python -m ruff check .        # E/F/W/B/UP 等规则
```

测试覆盖：列表页解析、两代详情模板（2000 旧版 / 2011 / 问答体 / 新闻稿体）、噪声清洗、
问答配对、md↔record 往返无损、渲染幂等、jsonl 布局、front matter 空值边界、sha 稳定性、
db 覆盖写与检索、原子写无残留、单期处理幂等、篡改检测、多词 AND 与短词回退。

修改代码后建议跑的闭环：

```bash
python -m pytest tests -q && python -m ruff check . && python scrape_gtb.py verify
```

## 常见问题

<details>
<summary><b>刚 clone 下来，search / stats / verify 报错？</b></summary>

先执行 `python scrape_gtb.py rebuild` 生成 `gtb.db`。仓库不含数据库（可确定性重建，避免入库 30 MB 二进制）。
</details>

<details>
<summary><b>只想读正文，需要构建吗？</b></summary>

不需要。`data/*.md` 是完整成品，任何 Markdown 编辑器 / 脚本都能直接读。
</details>

<details>
<summary><b>rebuild 会联网吗？会不会覆盖我的改动？</b></summary>

不联网，只读本地 `raw/` 与 `data/*.md`。它会**重写** md 正文 —— 正文来自 `raw/`，
所以手工改 md 正文会被覆盖（`verify` 也会先报 `sha-mismatch`）。要长期修改请改 `raw/` 或清洗逻辑。
</details>

<details>
<summary><b>为什么有些期没有问答（qa: 0）？</b></summary>

只有 1 期（2000 年最早的一期，纯新闻稿体）没有问答结构，`qa` 为 0，正文仍在 md 中。
另有 2 组问答存在空问/空答，`verify` 以「提示」而非错误列出。
</details>

<details>
<summary><b>搜索为什么能查单个汉字？</b></summary>

FTS5 的 `trigram` 分词器按 3 字符窗口建索引，任意子串命中；本项目额外为 1–2 字查询加了 `LIKE` 回退。
</details>

<details>
<summary><b>抓取被别人跑会不会给站点压力？</b></summary>

默认 6 并发、最多 3 次重试（退避 1.5 s / 3 s / 4.5 s）、30 s 超时。自律起见可 `--workers 1`，并避免频繁 `--force` 全量重抓。
</details>

<details>
<summary><b>能换数据源 / 加别的栏目吗？</b></summary>

见[适配与扩展](#适配与扩展)。
</details>

## 已知局限

- **极少数早期稿件无问答结构**：仅 2000 年 1 期是纯新闻稿体（`qa` 为 0），正文仍完整保留。
- **站点改版即失效**：当前解析依赖 GBK 静态页与两代 DOM 模板；若改成 JSON 接口或前端渲染，需改 `collect_index()` / `parse_article()`。
- **单一栏目**：只覆盖「新闻发布会辑录」，不含例行发布会之外的声明、答问、专题。
- **未做实体归一**：同一发言人不同年份可能带职务前缀，未合并；未做繁简转换、未做人名识别。
- **无增量 append 日志**：`db` 每次整期覆盖写（保证幂等），不做历史版本留存。
- **平台**：在 macOS + Python 3.9 / 3.12 实测；代码只用标准库与 `os.replace`，理论上跨平台，**Windows/Linux 未实测**。

## 适配与扩展

| 需求 | 改哪里 |
|---|---|
| 站点换域名 / 栏目 | `BASE` 常量 |
| 列表页结构变化 | `collect_index()`（分页规律 `index.htm` / `index_N.htm`，50 条/页） |
| 详情页模板变化 | `parse_article()` + `paragraphs()`（`div.TRS_Editor` / `div#contentArea` 两代） |
| 新增噪声规则 | `polish()` 与 `HTML_LEAK_RE` |
| 问答配对规则 | `split_blocks()` / `classify()` / `extract_qa()` |
| 新增输出格式 | `build_record()` 之后加序列化函数，`save_record()` 里落盘 |
| 换数据库 / 加字段 | `db_connect()` 建表语句 + `db_upsert()` + `verify()` 同步加检查项 |

改完记得：`pytest` → `ruff` → `rebuild` → `verify`，四步都绿再提交。

## 版权与许可

- **代码**：MIT，见 [`LICENSE`](LICENSE)。
- **语料**：文字内容版权归**国务院台湾事务办公室**（<https://www.gwytb.gov.cn>）所有。
  本仓库仅出于研究、教学与文本分析目的做格式转换与结构整理：

  > **不得用于商业用途，不得转售，不得以本仓库形式再次公开发布全文语料。**
  > 引用请标注原始出处与原文链接。

- 抓取遵守站点公开可访问范围，未绕过任何访问控制或鉴权。

学术引用建议：

```text
国务院台湾事务办公室. 新闻发布会文字实录（2000-09-05 至 2026-10-21）[DB/OL].
https://www.gwytb.gov.cn/xwdt/xwfb/xwfbh/（经 gtb_scraper 转换整理）
```

数据集引用（Harvard Dataverse 存档）：

```text
Bin Liang, 2026, "Taiwan Affairs Office (TAO) Press Conference Transcript Corpus: 441 Sessions and 7,597 Q&A Pairs (2000-2026)", https://doi.org/10.7910/DVN/YHDWIJ, Harvard Dataverse, V1
```

## 变更记录

完整版本演进（含修复项与优化项）见 [`CHANGELOG.md`](CHANGELOG.md)。下表为 v1 → v2 的升级对照，
表中数据均为本次实测。

| 维度 | v1（2026-10-20 首版） | v2（本项目） |
|---|---|---|
| 形态 | 单次抓取脚本，跑完即止 | 单文件多子命令 CLI：`sync / rebuild / index / verify / stats / search / export` |
| 产物 | 仅 `data/*.md` + `report.json` | md + **JSONL 问答对** + **SQLite（FTS5 trigram 中文检索）** + 合并导出 + `index.md` |
| 全文检索 | 无（只能 `grep`） | `search 关键词`：1 字起可查，命中定位到「期号 + 问答序号 + 提问方/发言人」 |
| 离线重建 | 无（重跑必须联网） | `rebuild`：以 `raw/` 原始快照为权威源，**零网络**重建全部产物 |
| 幂等性 | 未定义 | 正文 sha16 指纹 + 结构化输出，**重跑零变更**（实测 442 请求后 1,323 个文件哈希全同） |
| 增量能力 | 每次全量 | 按日期/缓存跳过，`--since` / `--limit` / `--force` 可选 |
| 数据一致性 | 无检查机制 | `verify`：md ↔ jsonl ↔ db ↔ FTS 四方比对，异常退出码非 0，`--fix` 可反修 |
| 质量保障 | 无测试 | **20 项 pytest**（真实页面 fixture：两代模板/问答式/旧版）+ `ruff` 零告警 |
| 错误处理 | 失败仅打印 | 单篇失败不影响整体，明细入 `log/`，结束汇总 `new/updated/same/cached/失败` |
| 写盘安全 | 直接覆盖 | 原子写（`.tmp` + `os.replace`），中断不留半成品 |
| 文档 | README 一段说明 | README（格式契约/扩展指南）+ CHANGELOG + LICENSE（代码 MIT / 语料版权声明）+ pytest.ini + ruff.toml |
| 体积 | — | DB 经 FTS5 external-content 优化 55.6 MB → **30.8 MB** |
