# 本机 Zotero 本地 API 参考

Zotero 桌面版本机接口 = **Web API v3 的本地实现**，基址 `http://127.0.0.1:23119/api/...`，
用户库固定是 `/api/users/0`。

## 0. 两套接口，别混用

| | connector 接口 | 本地 API |
|---|---|---|
| 路径 | `/connector/...` | `/api/...` |
| 默认状态 | 通常开 | **默认关**（需用户手动勾选） |
| 建分类 / 改条目 / 删条目 | ❌ 没有这些端点 | ✅ |
| 导入新条目 | ✅ | ✅ |
| **给「已存在」条目挂 PDF** | ❌ 只能给本次会话新建的条目挂 | ✅ |
| 条目里的 `attachments` 字段 | ⚠️ **被刻意忽略** | 适用 |

结论：**凡是涉及「已存在条目」或「分类/删除」的操作，一律走本地 API**；connector 只在
本地 API 确实无法开启时作为降级方案。

## 1. 开启开关

Pref `extensions.zotero.httpServer.localAPI.enabled`，界面位置：
**编辑 → 设置 → 高级 → 杂项 →「允许此计算机上的其他应用程序与 Zotero 通讯」**。
每次请求时校验，**勾选后立即生效，无需重启**。若返回
`403 ... Local API is not enabled`，就是这个开关没开。

## 2. 授权（写操作必需）

```
POST /api/local/authorize
Content-Type: application/json
Zotero-Server-ID: <server id>

{"appName": "WorkBuddy 文献助手"}
-> {"key": "<api key>", ...}
```

- 会弹出 Zotero 授权窗口。用户点「**始终允许**」后，key 会被持久化到
  `<配置目录>/localAPIKeys.json`，后续可复用；点「允许一次」则是一次性 key。
- `Zotero-Server-ID` 缺失会 `428`，不匹配会 `412`。可从任意响应头 `Zotero-Server-ID` 取。
  客户端的 `_detect_server_id()` 就是这么做的。
- `scripts/zotero_client.py` 的 `_load_key()` 会优先复用 `localAPIKeys.json` 里已存 key，
  没有才去申请（避免每次弹窗）。

## 3. 写操作的三条硬性要求

1. header 必带 `Zotero-Server-ID`
2. **每条写请求必带 `If-Unmodified-Since-Version: <version>`**，否则 `428
   If-Unmodified-Since-Version not provided`。version 先 `GET` 该对象取 `version` 字段。
   客户端的 `set_item_fields()` / `delete_item()` 已自动处理。
3. **建分类 / 建条目的 body 必须是 JSON 数组**：`[{"name":"..."}]`、`[{...}]`。
   传单个对象会 `400 Uploaded data must be a JSON array`。

## 4. 常用端点

| 操作 | 请求 |
|---|---|
| 列条目 | `GET /api/users/0/items?limit=100[&includeTrashed=1]` |
| 取条目 | `GET /api/users/0/items/<KEY>` |
| 子项 | `GET /api/users/0/items/<KEY>/children` |
| 建条目 | `POST /api/users/0/items`，body 为数组（单次 ≤ 50） |
| 改条目 | `PATCH /api/users/0/items/<KEY>` |
| 删条目 | `DELETE /api/users/0/items/<KEY>`（**永久**） |
| 列分类 | `GET /api/users/0/collections` |
| 建分类 | `POST /api/users/0/collections`，body `[{"name":..,"parentCollection":false}]` |
| 删分类 | `DELETE /api/users/0/collections/<KEY>` |
| 分类内条目 | `GET /api/users/0/collections/<KEY>/items/top` |
| 字段白名单 | `GET /api/itemTypeFields?itemType=preprint`（不带参数 400） |

写完成后返回 `204`（成功但无内容）或 `200/201`（带 body）。
新建条目成功返回 `{"successful": {"0": {"data": {"key": ...}}}, "failed": {...}}`。

## 5. 给条目挂 PDF（三步上传）

1. **建附件条目**
   `POST /api/users/0/items`
   ```json
   [{"itemType":"attachment","linkMode":"imported_file","parentItem":"<父KEY>",
     "title":"...","filename":"a.pdf","contentType":"application/pdf",
     "tags":[],"collections":[],"relations":{}}]
   ```
2. **申请上传**
   `POST /api/users/0/items/<ATT>/file`
   header `If-None-Match: *`，表单（`application/x-www-form-urlencoded`）：
   `md5`、`filename`、`filesize`、`mtime`（毫秒）、`contentType`
   → 返回 `{"url": "...", "uploadKey": "..."}`
3. **传字节**
   `POST <url>`（形如 `/api/local/uploads/<uploadKey>`），body 为 PDF 原始字节，
   header `Content-Type: application/pdf`。**这一步不需要 key/Server-ID。** → `201`
4. **登记落盘**
   `POST /api/users/0/items/<ATT>/file`，header `If-None-Match: *`，表单 `upload=<uploadKey>`
   → `204`。此后文件在 `<数据目录>/storage/<ATT>/<filename>`。

把附件**改挂**到别的父条目：`PATCH /api/users/0/items/<ATT>` body `{"parentItem":"<新父KEY>"}`
——文件不移动，只改归属。这比重新上传省事得多。

## 6. 只读校验（不碰正在运行的库）

需要交叉验证写入结果时：把 `<数据目录>/zotero.sqlite` 与 `zotero.sqlite-wal` 复制到临时目录，
再用 sqlite3 只读查询（`items` / `itemData` / `itemDataValues` / `fields` / `itemAttachments` /
`collections` / `collectionItems` / `itemNotes`）。**不要**直接打开用户的原库。

## 7. 其他注意

- 网络：访问 `127.0.0.1` **必须绕过代理**（`ProxyHandler({})` 或 `curl --noproxy '*'`），
  否则会被系统代理拦截报 502/超时；反过来访问 arXiv 等外网**必须走代理**。
- 单次写入对象数上限 50。
- `--dry-run` 覆盖所有写命令，先跑再实做。
