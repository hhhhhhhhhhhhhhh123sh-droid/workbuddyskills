# Zotero Library Manager

> 让 AI 助手（或你自己）直接读写本机 **Zotero 桌面版**文库的 Agent Skill，也可当纯命令行工具使用。

**English summary** — An agent skill (WorkBuddy / Claude-style) that manages your **local Zotero desktop library** on Windows: create and organize collections, import papers from arXiv together with their full-text PDFs, attach a PDF to an existing item, batch-edit fields, fix item ordering, write notes, run a library health check, and find duplicate items. Pure Python standard library — **zero dependencies**.

---

## 为什么需要它

Zotero 桌面版有**两套**本地接口，能力完全不同，混用会**静默失败**：

|                | connector 接口 `/connector/*`  | 本地 API `/api/*` |
| -------------- | ---------------------------- | --------------- |
| 默认状态           | 装了浏览器插件就有                    | **默认关闭，需手动开启**  |
| 新建条目           | ✅                            | ✅               |
| 给条目挂 PDF       | ❌ **会静默忽略 `attachments` 字段** | ✅               |
| 建分类 / 改字段 / 删除 | ❌ 完全不支持                      | ✅               |
| 写入授权           | 无                            | 首次写入弹窗授权        |

网上多数教程教你直接 POST 一个带 `attachments` 的条目 —— 结果是**附件根本没挂上，而且不报任何错**。这个技能把正确路径固化了下来：条目走 `/api/items`，PDF 走「建附件条目 → 上传字节 → 确认落盘」三步。

## 环境要求

- **Windows**（路径探测与授权文件读取按 Windows 布局实现；核心逻辑是纯 HTTP，其他平台需自行调整）
- **Zotero 10+ 桌面版**（开发与实测基于 Zotero 10.0.6）
- **Python 3.8+**，无需 `pip install` 任何东西

## 安装

### 1. 开启 Zotero 本地 API（必须，一次性）

> **编辑 → 设置 → 高级 → 杂项 → 勾选「允许此计算机上的其他应用程序与 Zotero 通讯」**

勾选后**立即生效，无需重启**。首次写入时 Zotero 会弹窗询问，选「**始终允许**」，这样只弹这一次。  
（随时可在同一位置取消勾选，或用旁边的按钮清除写入授权。）

### 2. 安装技能

```bash
git clone https://github.com/hhhhhhhhhhhhhhh123sh-droid/workbuddyskills.git \
  ~/.workbuddy/skills/zotero-library-manager
```

装好后**新开一个会话**，Agent 会在可用技能列表里自动发现它。以后更新只需在该目录里 `git pull`。

不想装成技能，也可以直接把它当命令行工具用：

```bash
cd ~/.workbuddy/skills/zotero-library-manager/scripts
python zotero_tool.py doctor
```

## 快速开始

```bash
cd scripts
python zotero_tool.py doctor   # 先自检：Zotero 在跑吗？本地 API 开了吗？拿到写入授权了吗？
```

`doctor` 全绿之后：

```bash
# 从 arXiv 导入论文（抓元数据 + 下载 PDF + 建条目 + 挂全文附件）
python zotero_tool.py import-arxiv 1506.01497 2005.12872 --collection 待读论文 --tag 目标检测

# 给**已有**条目补挂 PDF（connector 接口做不到这件事）
python zotero_tool.py attach ABC123XY "D:/papers/faster-rcnn.pdf"

# 全库体检 / 查重（只读，随便跑）
python zotero_tool.py scan
python zotero_tool.py dedupe --loose
```

## 命令一览

| 命令                                                                                    | 说明                          |
| ------------------------------------------------------------------------------------- | --------------------------- |
| `doctor`                                                                              | 环境自检（**先跑这个**）              |
| `collections`                                                                         | 列出所有分类                      |
| `list [--collection 名称] [--limit N]`                                                  | 列出条目                        |
| `show <KEY>`                                                                          | 查看条目完整字段 + 子项               |
| `import-arxiv <ID...> [--collection N] [--tag X] [--pdf-dir D] [--no-pdf] [--type T]` | arXiv 抓取 + 下载 PDF + 入库（含附件） |
| `attach <ITEM_KEY> <PDF路径>`                                                           | 给已有条目补挂 PDF                 |
| `note <ITEM_KEY> --text "…" \| --file F`                                              | 给条目加一条笔记                    |
| `add-to-collection <KEY...> --collection N`                                           | 把条目加入分类                     |
| `set-field <KEY> KEY=VALUE …`                                                         | 修改条目字段                      |
| `order --collection N <KEY...>`                                                       | 固定分类内的显示顺序                  |
| `scan [--limit N] [--trashed] [--json]`                                               | 全库体检（只读）                    |
| `dedupe [--loose [N]] [--json]`                                                       | 查重复条目（只报告，**不删除**）          |
| `delete <KEY> --yes`                                                                  | **永久删除**（不进回收站，不可恢复）        |

所有写命令都支持 `--dry-run`，先看效果再实做。

### `scan` 检查哪些问题

- **真问题**：空标题题录 · 附件标题是 `PDF` 或空 · **附件文件缺失**（库里有条目，`storage/` 里没文件）
- **提示项**：附件标题是 `Full Text PDF` 或文件名（Zotero 默认名，合法但看不出是哪篇）· 题录没挂 PDF · 题录未归入任何分类

### `dedupe` 怎么判重

默认**精确**：题名归一化（转小写、去标点空格）后完全一致，**或** DOI 相同。  
`--loose` 改为按题名前 N 字符（默认 45）归组，能抓出「副标题略有差异」的重复。  
每组会给出**建议保留项**（附件最多者优先，并列时取最早的 `dateAdded`），但**绝不自动删除** —— 确认后用 `delete <KEY> --yes` 手动清理。

## 两个必须搞懂的概念

**① 题录 ≠ 附件。** Zotero 里「条目」分两种：**题录**（`journalArticle` / `conferencePaper` / `preprint`，有标题作者年份，能生成参考文献）和**附件**（`attachment`，就是 PDF 文件本身，**只有「标题」一个字段**）。把 PDF 拖进 Zotero 但没识别出文献信息时，附件标题会被默认设成 `PDF` —— 用户抱怨的「文章不显示标题」多半就是这个。列表里显示成 `[文档]` 的，则是标题全空的题录（`getDisplayTitle()` 的兜底显示）。

**② 顺序靠「添加日期」。** Zotero 桌面端**不支持**在分类里手动拖拽排序。想固定顺序只能改条目的 `dateAdded`：该列默认 `sortReverse`（**最新在最上**），所以「第 1 篇」要给**最大**的时间戳。`order` 子命令已封装这件事。

## 常见坑速查

| 现象                                    | 原因 / 对策                                                                |
| ------------------------------------- | ---------------------------------------------------------------------- |
| 条目建了但 PDF 没挂上，且不报错                    | connector 接口**故意忽略** `attachments`；改用本地 API 三步上传                       |
| 写入返回 `428`                            | 缺 `Zotero-Server-ID` 或 `If-Unmodified-Since-Version` 头                 |
| 写入返回 `412`                            | `Zotero-Server-ID` 不匹配（Zotero 重启后会变，需重新探测）                             |
| 返回 `403` / `Local API is not enabled` | 本地 API 没开，去设置里勾选                                                       |
| 建分类 / 建条目返回 `400`                     | 请求体必须是 JSON **数组**，传对象会 400                                            |
| 访问本机接口 502 / 超时                       | 系统代理拦截；访问 `127.0.0.1` 必须**绕过代理**                                       |
| 删除后回收站里找不到                            | 本机 API 的 `DELETE` 是**永久删除**，`includeTrashed=1` 也查不到                    |
| 分类里排不了序                               | 不支持手动拖拽；改 `dateAdded`（该列默认最新在最上）                                       |
| arXiv 条目类型总是 `preprint`               | arXiv 的 Atom 接口常不返回 `journal_ref`/`comment`，无法推断会议/期刊；用 `--type` 手动指定  |
| 想校验数据又不敢动库                            | **别**直接改 `zotero.sqlite`（运行时锁库）；复制 `zotero.sqlite` + `-wal` 到临时目录后只读查询 |

更详细的接口与坑位记录见 [`references/local-api.md`](references/local-api.md) 与 [`references/gotchas.md`](references/gotchas.md)。

## 目录结构

```
.
├── SKILL.md                  Agent 入口（技能主文件）
├── README.md
├── LICENSE
├── references/
│   ├── local-api.md          本机 API 端点、授权流程、错误码、PDF 三步上传
│   └── gotchas.md            数据模型与 UI 的坑
└── scripts/
    ├── zotero_client.py      核心库：环境探测 / 授权 / 读写封装 / 附件上传
    ├── zotero_tool.py        CLI 入口（全部子命令）
    ├── arxiv.py              arXiv 元数据抓取 + PDF 下载
    └── selftest.py           读写能力自检（跑完自动清理，不留残留）
```

## 安全说明

- **凭据**：API key 由 Zotero 在本机生成、保存在其配置目录的 `localAPIKeys.json`。脚本**只读不复制**，不落盘到仓库、不外发。
- **网络**：仅访问 `http://127.0.0.1:23119`（本机 Zotero）与 `export.arxiv.org`（抓论文元数据/PDF）。**没有任何向第三方服务器外发数据的行为**。
- **破坏性操作**：`delete` 是永久删除，必须显式加 `--yes`；不加只打印清单并中止。`scan` / `dedupe` 完全只读。
- **不碰数据库文件**：全部通过 Zotero 官方 HTTP 接口操作，不直接读写 `zotero.sqlite`。

## 许可

[MIT](LICENSE)
