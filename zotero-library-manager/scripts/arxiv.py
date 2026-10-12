# -*- coding: utf-8 -*-
"""
arxiv.py —— 抓取 arXiv 论文元数据 + 下载 PDF。

注意：访问外网**必须走系统代理**（环境变量 HTTPS_PROXY/HTTP_PROXY），
与访问本机 Zotero（必须绕过代理）正好相反。

用法：
    from arxiv import fetch_metadata, download_pdfs
    meta = fetch_metadata(["1506.01497", "2005.12872"])   # -> {id: {...}}
    download_pdfs(meta, "pdf")                            # -> {id: 本地路径}
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "http://export.arxiv.org/api/query?id_list=%s&max_results=%d"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _opener():
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (zotero-library-manager)")]
    return op


def _txt(el, tag, ns="a"):
    if el is None:
        return ""
    node = el.find("%s:%s" % (ns, tag), NS)
    return " ".join(node.text.split()) if node is not None and node.text else ""


def fetch_metadata(ids, retries=3):
    """按 arXiv 编号抓元数据。返回 {arxiv_id: {title, abstract, published, authors, ...}}。"""
    ids = [re.sub(r"^arxiv:", "", i.strip(), flags=re.I) for i in ids]
    op = _opener()
    url = ATOM % (",".join(ids), max(20, len(ids)))
    raw = None
    for attempt in range(retries):
        try:
            raw = op.open(url, timeout=90).read()
            break
        except Exception as e:
            if attempt == retries - 1:
                raise
            print("   [重试 %d] %s" % (attempt + 1, e))
            time.sleep(3)
    root = ET.fromstring(raw)
    out = {}
    for e in root.findall("a:entry", NS):
        short = e.find("a:id", NS).text.strip().rsplit("/abs/", 1)[-1]
        base = re.sub(r"v\d+$", "", short)
        authors = []
        for a in e.findall("a:author", NS):
            name = " ".join(a.find("a:name", NS).text.split())
            parts = name.rsplit(" ", 1)
            authors.append({"creatorType": "author",
                            "firstName": parts[0] if len(parts) > 1 else "",
                            "lastName": parts[-1]})
        out[base] = {
            "arxiv_id": base,
            "title": _txt(e, "title"),
            "abstract": _txt(e, "summary"),
            "published": _txt(e, "published")[:10],
            "authors": authors,
            "journal_ref": _txt(e, "journal_ref", "arxiv"),
            "doi": _txt(e, "doi", "arxiv"),
            "comment": _txt(e, "comment", "arxiv"),
            "pdf_url": "https://arxiv.org/pdf/%s" % base,
        }
    return out


def guess_item_type(meta):
    """按 journal_ref / comment 猜条目类型（preprint / conferencePaper / journalArticle）。"""
    j = (meta.get("journal_ref") or "").lower()
    c = (meta.get("comment") or "").lower()
    blob = j + " " + c
    if any(w in blob for w in ("cvpr", "iccv", "eccv", "neurips", "nips", "icml", "iclr",
                               "aaai", "ijcai", "icip", "wacv", "bmvc", "conference",
                               "proceedings", "symposium", "workshop")):
        return "conferencePaper"
    if meta.get("journal_ref"):
        return "journalArticle"
    return "preprint"


def download_pdfs(meta, out_dir, delay=1.5):
    """下载 PDF 到 out_dir，返回 {arxiv_id: 本地路径}。已存在则跳过。"""
    os.makedirs(out_dir, exist_ok=True)
    op = _opener()
    saved = {}
    for aid, m in meta.items():
        # 文件名尽量用论文标题，去掉非法字符
        safe = re.sub(r'[\\/:*?"<>|]', "_", m["title"])[:80].strip() or aid
        path = os.path.join(out_dir, "%s_%s.pdf" % (aid, safe))
        if os.path.exists(path) and os.path.getsize(path) > 10240:
            saved[aid] = path
            continue
        try:
            blob = op.open(m["pdf_url"], timeout=180).read()
            if not blob.startswith(b"%PDF"):
                print("   [跳过] %s 返回的不是 PDF（可能被限流）" % aid)
                continue
            with open(path, "wb") as f:
                f.write(blob)
            saved[aid] = path
            print("   [已下载] %s  %s  (%.1f MB)" % (aid, os.path.basename(path), len(blob) / 1e6))
        except Exception as e:
            print("   [失败] %s : %s" % (aid, e))
        time.sleep(delay)
    return saved
