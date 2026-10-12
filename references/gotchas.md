# Zotero 数据模型与 UI 的坑

## 1. 题录 vs 附件（最常被误解的一件事）

Zotero 里的「条目」有两类，字段结构完全不同：

| | 题录（regular item） | 附件（attachment） |
|---|---|---|
| itemType | journalArticle / conferencePaper / preprint / document … | `attachment` |
| 有标题？ | ✅ | ✅（但**只有标题**这一个可读字段） |
| 有作者/年份/期刊？ | ✅ | ❌ |
| 能生成参考文献？ | ✅ | ❌ |
| 子项 | 可挂附件与笔记 | 无 |

**「这条文献不显示标题」的真相**：用户看到的 `PDF` 其实是一条**附件**的名字。当 PDF 被拖进
Zotero 而没能识别出文献信息时，Zotero 就把附件标题默认设成 `PDF`。它**不是**不显示标题，
而是它的标题**本来就叫 PDF**。

另一种情况是**标题为空的题录**：`item.js` 的 `getDisplayTitle()` 在标题为空时兜底显示
`[本地化的条目类型名]`——所以一条空的 `document` 会显示成 `[文档]`。

**处理办法**
- 附件标题想改 → 直接 `PATCH` 该附件的 `title`。
- 那条 `[文档]` 之类空题录下挂着一堆 PDF → 用 arXiv/DOI 元数据**新建正式题录**，
  再用 `PATCH parentItem` 把附件**改挂**过去，最后删掉空题录。
- 独立 PDF（没有父条目）→ 也可以在 Zotero UI 里右键「检索 PDF 元数据」。
- 补充：PDF 内嵌的 `/Title` 常常是空的，所以自动识别失败很常见；
  Zotero 自己保存文献时附件默认叫 `Full Text PDF`，而导入下载的常是 `_.pdf`
  或 `作者 等 - 年份 - 标题.pdf`。**附件的物理文件名在导入时就固定了**，
  改标题不会改文件名。

## 2. 排序：桌面端不能手动拖拽

- `collectionItems.orderIndex` 字段确实存在，加入分类时按 `MAX(orderIndex)+1` 写，
  但**桌面 UI 不读取它**（保留给 web 端）。
- 唯一可靠的「固定顺序」办法是改 `dateAdded`。**关键**：`itemTreeColumns.js` 里
  `dateAdded` 带 `sortReverse: true`，`virtualized-table.js` 中
  `column.sortDirection = sortReverse ? -1 : 1` → 首次点该列是**降序（最新在最上）**。
  所以「第 1 篇」要给**最大**的时间戳。
- 取时间戳一律用 UTC（`Z` 结尾），否则会差时区偏移。
- 不想改字段的替代方案：标题加 `01 ·` 前缀，或在分类下建 `01`…`12` 子分类。

## 3. connector 接口的能力边界（别指望它）

- Zotero 10 的 `/connector/saveItems` **会刻意忽略条目里的 `attachments` 字段**
  （源码 `saveSession.js` 里 `ATTACHMENT_MODE_IGNORE`，注释写着
  "All attachments come from the Connector"）。挂 PDF 必须另走
  `POST /connector/saveAttachment?sessionID=<同>`，header `X-Metadata` 里带
  `parentItemID`，body 为 PDF 字节。两步要用同一个 `sessionID`，会话约 10 分钟过期。
- 它**不能**给「已存在」的条目补挂附件（`session.getItemByConnectorKey` 只认本次会话新建的
  条目），也没有建分类/改/删的端点。这些只能靠本地 API。

## 4. 删除的语义

- **本地 API 的 `DELETE` 是永久删除**：返回 204 后条目直接消失，不进回收站，
  连 `?includeTrashed=1` 也查不到。
- UI 里按 Delete 才是「移入回收站」。两者行为不同，**不能混为一谈**。
- 因此：删除前必须先 `show` 确认内容与子项，把清单交用户确认，再执行。

## 5. 其他细节

- 附件用 `imported_file`（文件存进 `storage/<附件KEY>/`）与 `linked_file`（只存外部路径）
  两种 linkMode；本技能统一用前者。
- `dateModified` 与 `dateAdded` 是两回事：改字段会更新前者，不一定会动后者。
- 库结构上，`storage/<ITEM_KEY>/` 目录名是**附件条目的 key**，不是父条目的 key。
