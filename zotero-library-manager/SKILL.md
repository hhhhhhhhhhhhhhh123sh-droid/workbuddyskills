---
name: zotero-library-manager
description: 操作本机 Zotero 桌面版（Windows）的文献库——新建/整理分类、把 arXiv 论文抓取并导入 Zotero（含 PDF 全文附件）、给已有条目补挂 PDF、批量修改字段或调整列表顺序、写入中文导读笔记、全库体检（空标题/附件标题异常/缺 PDF/文件丢失/未分类）与查重复条目、安全删除条目，并解释「这条文献为什么不显示标题」这类数据模型问题。当用户提到 Zotero、文库、文献管理、导入论文到 Zotero、给文献分类/排序/打标签、补 PDF 附件、Zotero 笔记、Zotero 库太乱/有重复等时使用。
agent_created: true
---

# Zotero 文库管理

在本机 Zotero 桌面版上做文献库读写。目标是**别再重新踩一遍那些反直觉的坑**：本机
Zotero 有两套接口，能力完全不同，混用会静默失败。

## 何时使用

- 用户要把论文导入 Zotero（尤其从 arXiv）、给文献分类/排序/打标签、补挂 PDF
- 用户问「Zotero 里某条为什么不显示标题 / 为什么叫 PDF / 为什么顺序不对」
- 用户要批量改条目字段、加导读笔记、清理空条目

## 先做这两步（不要跳过）

1. `python scripts/zotero_tool.py doctor`
   检查：Zotero 是否运行、**本地 API 是否开启**、是否有写入授权、目录与 Server-ID。
2. 若 doctor 报「本地 API 未开启」，**停下来让用户手动打开**：
   编辑 → 设置 → 高级 → 杂项 → 勾选「**允许此计算机上的其他应用程序与 Zotero 通讯**」
   （勾选后立即生效，无需重启）。然后首次写入时 Zotero 会弹窗，请用户点「**始终允许**」。
   没有这一步，一切写操作都无从做起。

需要验证写入能力（建分类、挂 PDF）时，跑 `python scripts/selftest.py`
（可选 `--with-pdf <路径>` 测附件上传；它会临时建条目并在结束时自动删除）。

## 常用操作

```bash
PY=python   # 用实际可用的 python；Windows 上建议用托管解释器的绝对路径

# 导入 arXiv 论文（抓元数据 + 下 PDF + 入库 + 挂附件）
$PY scripts/zotero_tool.py import-arxiv 1506.01497 2005.12872 \
        --collection 待读论文 --tag 目标检测

# 给**已有**条目补挂 PDF（connector 接口做不到这件事，必须走本地 API）
$PY scripts/zotero_tool.py attach <ITEM_KEY> "D:/papers/a.pdf"

# 建分类 / 归类 / 加笔记
$PY scripts/zotero_tool.py add-to-collection <KEY...> --collection 目标检测综述
$PY scripts/zotero_tool.py note <ITEM_KEY> --text "为什么读：……"

# 让分类里从上到下按给定顺序显示（改「添加日期」）
$PY scripts/zotero_tool.py order --collection 待读论文 K1 K2 K3

# 全库体检（只读）：空标题 / 附件标题异常 / 缺 PDF / 文件丢失 / 未分类
$PY scripts/zotero_tool.py scan
$PY scripts/zotero_tool.py scan --trashed --json

# 查重复条目（只报告，不删除）
$PY scripts/zotero_tool.py dedupe            # 精确：题名归一化一致，或 DOI 相同
$PY scripts/zotero_tool.py dedupe --loose    # 模糊：按题名前 45 字符归组

# 永久删除（务必先 show 确认、再加 --yes）
$PY scripts/zotero_tool.py show <KEY>
$PY scripts/zotero_tool.py delete <KEY> --yes
```

所有写命令都支持 `--dry-run`（命令前或后都可以），先跑一遍看效果再实做。
`scan` / `dedupe` 是**只读**的，不修改任何东西，可放心跑。

### scan 检查的六项

真问题：① 空标题题录；② 附件标题是 `PDF`/空（看不出是哪篇）；③ **附件文件缺失**
（库里有条目但 storage 里没有文件）。提示项：④ 附件标题是 `Full Text PDF` 或文件名
（Zotero 默认名，合法但看不出是哪篇）；⑤ 题录没挂 PDF；⑥ 题录未归入任何分类。
`--limit N` 控制每类列几条，`--json` 给机器读。

### dedupe 的判定

默认「精确」：题名归一化（转小写、去标点空格）后完全一致，**或** DOI 相同。
`--loose` 改为按题名前 N 字符（默认 45）归组，能抓「副标题略有差异」的重复。
每组会给出**建议保留项**（附件最多者优先，并列时取最早的 `dateAdded`），
但**绝不自动删除**——确认后用 `delete <KEY> --yes` 逐条删。

## 两个必须搞懂的概念

**① 题录 vs 附件。** Zotero 里「条目」分两种：*题录*（journalArticle / conferencePaper /
preprint，有标题作者年份，能生成参考文献）和*附件*（attachment，就是 PDF 文件本身，
只有「标题」一个字段）。把 PDF 拖进 Zotero 而没识别出文献信息时，附件的标题会被默认设成
`PDF`——用户说的「文章不显示标题」，多半就是这个。目录里那条 `[文档]` 则是标题全空的题录
（Zotero 兜底显示 `[类型名]`）。详见 `references/gotchas.md`。

**② 顺序靠「添加日期」。** Zotero 桌面端**不支持**在分类里手动拖拽排序。想固定顺序，
只能改条目的 `dateAdded`：该列默认 `sortReverse`（**最新在最上**），所以「第 1 篇」要给
**最大**的时间戳。`order` 子命令已封装这件事。备选方案是标题加序号前缀或拆子分类。

## 脚本

- `scripts/zotero_client.py` —— 核心库：环境探测、授权、读写封装、**PDF 三步上传**。
  `ZoteroClient().doctor()` 可独立使用。
- `scripts/zotero_tool.py` —— 命令行入口（子命令见文件头注释）。
  写操作：`import-arxiv` / `attach` / `note` / `add-to-collection` / `set-field` / `order` / `delete`；
  只读诊断：`doctor` / `collections` / `list` / `show` / **`scan`（体检）** / **`dedupe`（查重）**。
- `scripts/arxiv.py` —— arXiv 元数据抓取 + PDF 下载（注意：外网**必须走系统代理**，
  而访问本机 Zotero **必须绕过代理**，方向相反）。
- `scripts/selftest.py` —— 读写能力自检，跑完自动清理。

## 参考资料

- `references/local-api.md` —— 本机 API 的端点、授权流程、错误码（428/412/400）含义、
  上传协议、只读校验办法。
- `references/gotchas.md` —— 数据模型与 UI 的坑：附件标题、`getDisplayTitle` 兜底、
  connector 接口的能力边界、排序方向、storage 布局。

## 红线

- 本机 API 的 `DELETE` 是**永久删除**（不进回收站、`includeTrashed=1` 也查不到）。
  删之前先 `show`，把清单给用户确认，再带 `--yes`。
- **绝不要**直接改 `zotero.sqlite`（Zotero 运行时会锁库/覆盖）。要校验就复制 `zotero.sqlite`
  与 `-wal` 到临时目录后用 sqlite3 只读查询。
- 不要改动用户未要求的条目；批量操作前先列出受影响清单。
