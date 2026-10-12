# -*- coding: utf-8 -*-
"""
zotero_client.py —— 本机 Zotero 桌面版（Windows）读写客户端。

只用标准库（Python 3.8+），无需 pip 安装任何东西。

设计要点（这些都是实测踩坑后固化下来的）：
  * 访问 127.0.0.1 必须绕过系统代理，否则会被代理拦截（502/超时）。
  * 写操作必须带 `Zotero-Server-ID`，且必须带 `If-Unmodified-Since-Version`，否则 428。
  * 建分类 / 建条目提交的 body 必须是 JSON **数组**，传对象会 400。
  * 本机 API 的 DELETE 是**永久删除**（不进回收站），调用前必须确认。
  * 本地 API 未开启时返回 403 "Local API is not enabled"，需要用户在 Zotero 里手动勾选。

命令行入口见 zotero_tool.py。
"""

import glob
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:23119"
LIB = "/api/users/0"
API_VERSION = "3"


class ZoteroError(Exception):
    """带 HTTP 状态与响应体的错误。"""

    def __init__(self, status, body, hint=""):
        self.status = status
        self.body = body
        msg = "HTTP %s: %s" % (status, body)
        if hint:
            msg += "\n提示：" + hint
        super().__init__(msg)


class ZoteroClient:
    def __init__(self, app_name="WorkBuddy 文献助手", api_key=None,
                 server_id=None, base=BASE, lib=LIB, verbose=False):
        # 关键：显式清空代理，直连本机
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.base = base.rstrip("/")
        self.lib = lib
        self.app_name = app_name
        self.verbose = verbose
        self._key = api_key
        self.server_id = server_id or self._detect_server_id()
        if not self._key:
            self._key = self._load_key()

    # ------------------------------------------------------------ 环境探测
    @staticmethod
    def find_profile_dirs():
        """返回 Zotero 配置目录（含 prefs.js / localAPIKeys.json 的那个）。"""
        cands = []
        for env in ("APPDATA", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                cands += glob.glob(os.path.join(root, "Zotero", "Zotero", "Profiles", "*"))
        return [c for c in cands if os.path.isdir(c)]

    @classmethod
    def find_data_dir(cls):
        """返回 Zotero 数据目录（含 zotero.sqlite / storage）。"""
        guess = os.path.join(os.path.expanduser("~"), "Zotero")
        if os.path.exists(os.path.join(guess, "zotero.sqlite")):
            return guess
        for p in cls.find_profile_dirs():
            prefs = os.path.join(p, "prefs.js")
            if not os.path.exists(prefs):
                continue
            try:
                for line in open(prefs, encoding="utf-8", errors="replace"):
                    if "extensions.zotero.dataDir" in line and "user_pref" in line:
                        seg = line.split('"')
                        if len(seg) >= 4 and seg[3]:
                            d = seg[3].replace("\\\\", "\\")
                            if os.path.isdir(d):
                                return d
            except Exception:
                pass
        return guess if os.path.isdir(guess) else None

    def _keys_file(self):
        for p in self.find_profile_dirs():
            f = os.path.join(p, "localAPIKeys.json")
            if os.path.exists(f):
                return f
        return None

    def _load_key(self):
        """读 Zotero 自己保存的授权 key（用户点过「始终允许」才会有）。"""
        f = self._keys_file()
        if not f:
            return None
        try:
            data = json.load(open(f, encoding="utf-8"))
            keys = data.get("keys") or []
            if keys:
                return keys[-1].get("key")
        except Exception:
            pass
        return None

    def _detect_server_id(self):
        """从任意响应头取 Zotero-Server-ID（写操作必带，否则 428/412）。"""
        try:
            req = urllib.request.Request(self.base + self.lib + "/items?limit=1")
            with self.opener.open(req, timeout=15) as resp:
                sid = resp.headers.get("Zotero-Server-ID")
                if sid:
                    return sid
        except urllib.error.HTTPError as e:
            sid = e.headers.get("Zotero-Server-ID") if e.headers else None
            if sid:
                return sid
        except Exception:
            pass
        return None

    # ------------------------------------------------------------ 底层请求
    def _headers(self, extra=None):
        h = {"Zotero-API-Version": API_VERSION, "Connection": "close"}
        if self.server_id:
            h["Zotero-Server-ID"] = self.server_id
        if self._key:
            h["Zotero-API-Key"] = self._key
        if extra:
            h.update(extra)
        return h

    def authorize(self, timeout=180):
        """申请本机写入授权。Zotero 会弹窗，需要用户点「始终允许」。"""
        body = json.dumps({"appName": self.app_name}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Connection": "close"}
        if self.server_id:
            headers["Zotero-Server-ID"] = self.server_id
        req = urllib.request.Request(self.base + "/api/local/authorize",
                                     data=body, headers=headers, method="POST")
        with self.opener.open(req, timeout=timeout) as resp:
            self._key = json.loads(resp.read().decode("utf-8"))["key"]
        if self.verbose:
            print("   [授权] 已获得 API key")
        return self._key

    def request(self, method, path, body=None, form=None, extra=None,
                raw=False, auth_retry=True, timeout=90):
        """
        path 为 /api/... 全路径。body=JSON 对象/数组；form=表单字典；raw=返回原始 bytes。
        """
        url = self.base + path
        data = None
        headers = self._headers(extra)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else self._maybe_json(payload))
        except urllib.error.HTTPError as e:
            payload = e.read()
            text = payload.decode("utf-8", "replace")
            if "Local API is not enabled" in text:
                raise ZoteroError(e.code, text,
                                  "Zotero 的本地接口没开。请让用户在 "
                                  "「编辑 → 设置 → 高级 → 杂项」勾选"
                                  "「允许此计算机上的其他应用程序与 Zotero 通讯」，"
                                  "勾选后立即生效、无需重启。")
            if e.code == 401 and auth_retry:
                self.authorize()
                return self.request(method, path, body, form, extra, raw, False, timeout)
            raise ZoteroError(e.code, text)

    @staticmethod
    def _maybe_json(payload):
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception:
            return payload.decode("utf-8", "replace")

    # ------------------------------------------------------------ 读
    def items(self, limit=100, include_trashed=False, **params):
        q = {"limit": limit}
        if include_trashed:
            q["includeTrashed"] = 1
        q.update(params)
        return self.request("GET", "%s/items?%s" % (self.lib, urllib.parse.urlencode(q)))[1]

    def item(self, key):
        return self.request("GET", "%s/items/%s" % (self.lib, key))[1]

    def children(self, key):
        return self.request("GET", "%s/items/%s/children" % (self.lib, key))[1]

    def collections(self):
        return self.request("GET", "%s/collections" % self.lib)[1]

    def collection_items(self, key, top=True):
        suffix = "/items/top" if top else "/items"
        return self.request("GET", "%s/collections/%s%s" % (self.lib, key, suffix))[1]

    def find_collection(self, name):
        for c in self.collections():
            if c["data"]["name"] == name:
                return c["key"]
        return None

    def find_item_by_title(self, needle):
        out = []
        for it in self.items(limit=500):
            t = it["data"].get("title")
            if t and needle.lower() in t.lower():
                out.append(it)
        return out

    def all_items(self, include_trashed=False, page=100, max_pages=100):
        """自动翻页拉取全部条目（含附件与笔记），用于全库体检 / 查重。"""
        out, start = [], 0
        for _ in range(max_pages):
            q = {"limit": page, "start": start}
            if include_trashed:
                q["includeTrashed"] = 1
            batch = self.request(
                "GET", "%s/items?%s" % (self.lib, urllib.parse.urlencode(q)))[1]
            out += batch
            if len(batch) < page:
                break
            start += page
        return out

    def attachment_file_exists(self, att_key, filename):
        """
        校验附件对应的物理文件是否真的在 storage 里。
        返回 True/False；若无法定位数据目录则返回 None（未知）。
        """
        dd = self.find_data_dir()
        if not dd or not filename:
            return None
        return os.path.exists(os.path.join(dd, "storage", att_key, filename))

    # ------------------------------------------------------------ 写
    def create_collection(self, name, parent=None, dry_run=False):
        if dry_run:
            print("   [dry-run] 建分类 %r" % name)
            return None
        body = [{"name": name, "parentCollection": parent or False}]
        st, res = self.request("POST", "%s/collections" % self.lib, body=body)
        return res["successful"]["0"]["data"]["key"]

    def delete_collection(self, key, dry_run=False):
        if dry_run:
            print("   [dry-run] 删分类 %s" % key)
            return
        ver = self.request("GET", "%s/collections/%s" % (self.lib, key))[1]["version"]
        self.request("DELETE", "%s/collections/%s" % (self.lib, key),
                     extra={"If-Unmodified-Since-Version": str(ver)})

    def set_item_fields(self, key, fields, dry_run=False):
        """改条目字段（含 collections / dateAdded）。自动带上版本号。"""
        if dry_run:
            print("   [dry-run] 改 %s -> %s" % (key, json.dumps(fields, ensure_ascii=False)[:120]))
            return
        ver = self.item(key)["version"]
        self.request("PATCH", "%s/items/%s" % (self.lib, key), body=fields,
                     extra={"If-Unmodified-Since-Version": str(ver)})

    def add_to_collection(self, key, collection_key, dry_run=False):
        cur = self.item(key)["data"]
        cols = list(cur.get("collections") or [])
        if collection_key not in cols:
            cols.append(collection_key)
        self.set_item_fields(key, {"collections": cols}, dry_run=dry_run)
        return cols

    def create_items(self, payloads, dry_run=False):
        """payloads 为 list[dict]，单次上限 50 条。返回 {index: key}。"""
        if dry_run:
            print("   [dry-run] 新建 %d 条条目" % len(payloads))
            return {}
        if len(payloads) > 50:
            raise ValueError("单次最多 50 条")
        st, res = self.request("POST", "%s/items" % self.lib, body=payloads)
        out = {}
        for idx, item in (res.get("successful") or {}).items():
            out[int(idx)] = item["data"]["key"]
        if res.get("failed"):
            print("   [部分失败]", json.dumps(res["failed"], ensure_ascii=False)[:300])
        return out

    def create_note(self, parent_key=None, html="", collection_key=None, dry_run=False):
        payload = {"itemType": "note", "note": html, "tags": [],
                   "collections": [collection_key] if collection_key else [],
                   "relations": {}}
        if parent_key:
            payload["parentItem"] = parent_key
        if dry_run:
            print("   [dry-run] 建笔记 -> %s" % (parent_key or collection_key))
            return None
        return self.create_items([payload]).get(0)

    def delete_item(self, key, dry_run=False):
        """注意：本机 API 的删除是**永久**删除，不进回收站。"""
        if dry_run:
            print("   [dry-run] 永久删除 %s" % key)
            return
        ver = self.item(key)["version"]
        self.request("DELETE", "%s/items/%s" % (self.lib, key),
                     extra={"If-Unmodified-Since-Version": str(ver)})

    # ------------------------------------------------------------ 附件上传
    def create_attachment(self, parent_key, filename, title=None, dry_run=False):
        payload = {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "parentItem": parent_key,
            "title": title or os.path.basename(filename),
            "filename": os.path.basename(filename),
            "contentType": "application/pdf",
            "tags": [], "collections": [], "relations": {},
        }
        if dry_run:
            print("   [dry-run] 建附件条目 %s -> %s" % (payload["filename"], parent_key))
            return None
        return self.create_items([payload]).get(0)

    def upload_file(self, att_key, file_path, dry_run=False, timeout=600):
        """
        Zotero 新版直接上传三步：
          1) POST /items/<att>/file  表单 md5/filename/filesize/mtime/contentType + If-None-Match: *
             -> {url, uploadKey}
          2) POST <url>  原始字节 -> 201
          3) POST /items/<att>/file  表单 upload=<uploadKey> + If-None-Match: * -> 204 落盘
        """
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            md5 = hashlib.md5(f.read()).hexdigest()
        mtime = str(int(os.path.getmtime(file_path) * 1000))
        name = os.path.basename(file_path)
        if dry_run:
            print("   [dry-run] 上传 %s (%d bytes)" % (name, size))
            return
        st, res = self.request(
            "POST", "%s/items/%s/file" % (self.lib, att_key),
            form={"md5": md5, "filename": name, "filesize": str(size),
                  "mtime": mtime, "contentType": "application/pdf"},
            extra={"If-None-Match": "*"})
        url, upload_key = res["url"], res["uploadKey"]
        if url.startswith("/"):
            url = self.base + url
        with open(file_path, "rb") as f:
            blob = f.read()
        req = urllib.request.Request(url, data=blob, method="POST",
                                     headers={"Content-Type": "application/pdf",
                                              "Connection": "close"})
        with self.opener.open(req, timeout=timeout) as resp:
            if resp.status not in (200, 201):
                raise ZoteroError(resp.status, "上传字节失败")
        self.request("POST", "%s/items/%s/file" % (self.lib, att_key),
                     form={"upload": upload_key}, extra={"If-None-Match": "*"})

    def attach_pdf(self, item_key, file_path, title=None, dry_run=False):
        att = self.create_attachment(item_key, file_path, title=title, dry_run=dry_run)
        if dry_run:
            return None
        self.upload_file(att, file_path, dry_run=dry_run)
        return att

    # ------------------------------------------------------------ 自检
    def doctor(self):
        print("== Zotero 环境自检 ==")
        info = {}
        # 1. 进程/端口
        try:
            req = urllib.request.Request(self.base + "/connector/ping")
            with self.opener.open(req, timeout=10) as resp:
                info["running"] = resp.status == 200
        except Exception as e:
            info["running"] = False
            info["running_err"] = str(e)
        print("   1) Zotero 是否在运行 :", "是" if info["running"] else "否（请先启动 Zotero）")
        # 2. 本地 API
        try:
            st, _ = self.request("GET", "%s/items?limit=1" % self.lib, auth_retry=False)
            info["local_api"] = (st == 200)
        except ZoteroError as e:
            info["local_api"] = False
            info["local_api_body"] = (e.body or "")[:120]
        print("   2) 本地 API 是否开启 :", "是" if info.get("local_api") else "否")
        if not info.get("local_api"):
            print("      -> 让用户在「设置 → 高级 → 杂项」勾选"
                  "「允许此计算机上的其他应用程序与 Zotero 通讯」")
        # 3. key / 授权
        info["has_key"] = bool(self._key)
        print("   3) 是否已有写入授权 :", "是" if self._key else "否（首次写入会自动弹窗，请点「始终允许」）")
        # 4. 目录
        info["data_dir"] = self.find_data_dir()
        info["profile_dir"] = (self.find_profile_dirs() or [None])[0]
        info["server_id"] = self.server_id
        print("   4) Server-ID        :", self.server_id or "未取到")
        print("   5) 数据目录         :", info["data_dir"])
        print("   6) 配置目录         :", info["profile_dir"])
        if info.get("local_api"):
            try:
                its = self.items(limit=1)
                cols = self.collections()
                print("   7) 读数正常         : 条目可读，分类 %d 个" % len(cols))
            except Exception as e:
                print("   7) 读数异常         :", e)
        return info


if __name__ == "__main__":
    ZoteroClient(verbose=True).doctor()
