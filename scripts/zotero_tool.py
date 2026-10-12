# -*- coding: utf-8 -*-
"""
zotero_tool.py —— 本机 Zotero 文库操作的命令行入口。

子命令：
  doctor                                    环境自检（先跑这个）
  collections                               列出所有分类
  list [--collection 名称] [--limit N]      列出条目
  show <KEY>                                看某条目的完整字段 + 子项
  import-arxiv <ID...> [选项]               抓 arXiv 元数据 + 下载 PDF + 入库（含附件）
  attach <ITEM_KEY> <PDF路径>               给**已有**条目补挂 PDF
  note <ITEM_KEY> --text "..." | --file F   给条目加一条笔记
  add-to-collection <KEY...> --collection N 把条目加入分类
  set-field <KEY> KEY=VALUE ...             改条目字段
  order --collection N <KEY...>             按给定顺序设置「添加日期」（列表从上到下即顺序）
  scan [--trashed] [--json]                 全库体检：空标题 / 附件标题异常 / 缺 PDF / 文件丢失 / 未分类
  dedupe [--loose [N]] [--json]             查重复条目（只报告，不删除）
  delete <KEY> --yes                        永久删除条目（不可恢复！）

通用参数：--dry-run 只打印不写入。
示例：
  python zotero_tool.py doctor
  python zotero_tool.py import-arxiv 1506.01497 2005.12872 --collection 学习路线类 --tag 目标检测
  python zotero_tool.py attach ABC123XY "D:/papers/a.pdf"
  python zotero_tool.py order --collection 学习路线类 K1 K2 K3
  python zotero_tool.py scan
  python zotero_tool.py dedupe --loose
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zotero_client import ZoteroClient, ZoteroError  # noqa: E402
import arxiv  # noqa: E402


def _fields_whitelist(z, item_type):
    """取某条目类型的合法字段白名单（不含时退回通用集）。"""
    try:
        st, res = z.request("GET", "/api/itemTypeFields?itemType=%s" % item_type)
        return set(f["field"] for f in res)
    except Exception:
        return set()


def _filter(payload, allow):
    always = {"itemType", "creators", "tags", "collections", "relations"}
    if not allow:
        return payload
    return {k: v for k, v in payload.items() if k in allow or k in always}


def _resolve_collection(z, name, dry_run=False):
    if not name:
        return None
    key = z.find_collection(name)
    if key:
        return key
    print("   [提示] 分类 %r 不存在，将新建" % name)
    return z.create_collection(name, dry_run=dry_run)


# --------------------------------------------------------------------- 子命令
def cmd_doctor(args, z):
    z.doctor()


def cmd_collections(args, z):
    for c in z.collections():
        d = c["data"]
        print("  %s | %-28s | parent=%s" % (c["key"], d["name"], d.get("parentCollection")))


def cmd_list(args, z):
    if args.collection:
        ck = z.find_collection(args.collection)
        if not ck:
            sys.exit("找不到分类：%s" % args.collection)
        items = z.collection_items(ck)
    else:
        items = z.items(limit=args.limit)
    for it in items:
        d = it["data"]
        print("  %-9s %-18s | %s | %s" % (
            it["key"], d["itemType"], (d.get("title") or "(无标题)")[:56],
            ",".join(d.get("collections") or [])))


def cmd_show(args, z):
    it = z.item(args.key)
    d = it["data"]
    print(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True))
    kids = z.children(args.key)
    if kids:
        print("\n-- 子项 --")
        for c in kids:
            cd = c["data"]
            print("  %s | %s | title=%r | filename=%s" % (
                c["key"], cd["itemType"], cd.get("title"), cd.get("filename")))


def cmd_import_arxiv(args, z):
    ids = args.ids
    print("== 1. 抓取 arXiv 元数据 (%d 篇) ==" % len(ids))
    meta = arxiv.fetch_metadata(ids)
    missing = [i for i in ids if i not in meta]
    if missing:
        print("   [警告] 未取到的编号：", missing)
    if not meta:
        sys.exit("没有取到任何元数据，中止")

    coll_key = _resolve_collection(z, args.collection, dry_run=args.dry_run)

    print("== 2. 下载 PDF ==")
    pdf_dir = args.pdf_dir or os.path.join(os.getcwd(), "pdf")
    pdfs = {} if args.no_pdf else arxiv.download_pdfs(meta, pdf_dir)

    print("== 3. 写入 Zotero ==")
    order, payloads = [], []
    for aid, m in meta.items():
        itype = arxiv.guess_item_type(m) if args.type == "auto" else args.type
        extra = "arXiv: %s" % aid
        if m["comment"]:
            extra += "\nComment: " + m["comment"]
        p = {
            "itemType": itype, "title": m["title"], "creators": m["authors"],
            "abstractNote": m["abstract"], "date": m["published"],
            "url": "https://arxiv.org/abs/%s" % aid, "extra": extra,
            "tags": [{"tag": "arXiv:%s" % aid}] + [{"tag": t} for t in args.tag],
            "collections": [coll_key] if coll_key else [], "relations": {},
        }
        if m["doi"]:
            p["DOI"] = m["doi"]
        if itype == "conferencePaper" and m["journal_ref"]:
            p["proceedingsTitle"] = m["journal_ref"]
        if itype == "journalArticle" and m["journal_ref"]:
            p["publicationTitle"] = m["journal_ref"]
        p = _filter(p, _fields_whitelist(z, itype))
        payloads.append(p)
        order.append((aid, itype))

    created = z.create_items(payloads, dry_run=args.dry_run)
    for idx, (aid, itype) in enumerate(order):
        key = created.get(idx)
        print("   %s | %-16s | %s" % (aid, itype, (created.get(idx) or "(dry-run)")))
        if key and aid in pdfs:
            z.attach_pdf(key, pdfs[aid], title=meta[aid]["title"], dry_run=args.dry_run)
    print("== 完成：%d 篇 ==" % len(order))


def cmd_attach(args, z):
    if not os.path.exists(args.pdf):
        sys.exit("PDF 不存在：%s" % args.pdf)
    att = z.attach_pdf(args.key, args.pdf, title=args.title, dry_run=args.dry_run)
    print("   附件 key = %s" % att)


def cmd_note(args, z):
    if args.file:
        html = open(args.file, encoding="utf-8").read()
        html = "".join("<p>%s</p>" % ln for ln in html.splitlines() if ln.strip())
    else:
        html = args.text
    nk = z.create_note(parent_key=args.key, html=html, dry_run=args.dry_run)
    print("   笔记 key = %s" % nk)


def cmd_add_to_collection(args, z):
    ck = _resolve_collection(z, args.collection, dry_run=args.dry_run)
    for k in args.keys:
        z.add_to_collection(k, ck, dry_run=args.dry_run)
        print("   %s -> %s" % (k, args.collection))


def cmd_set_field(args, z):
    fields = {}
    for kv in args.pairs:
        if "=" not in kv:
            sys.exit("字段格式应为 KEY=VALUE：%s" % kv)
        k, v = kv.split("=", 1)
        fields[k.strip()] = v
    z.set_item_fields(args.key, fields, dry_run=args.dry_run)
    print("   已更新 %s: %s" % (args.key, list(fields)))


def cmd_order(args, z):
    """让分类里从上到下按给定顺序显示（依赖 Zotero「添加日期」列默认最新在上）。"""
    base = args.base or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    keys = args.keys
    n = len(keys)
    for i, k in enumerate(keys):
        # 第 1 个时间最新 -> 排最上
        dt = datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S") - datetime.timedelta(seconds=i)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        z.set_item_fields(k, {"dateAdded": ts}, dry_run=args.dry_run)
        print("   %02d %s -> %s" % (i + 1, k, ts))
    print("   提示：在 Zotero 该分类里点「添加日期」列头（默认最新在上）即为该顺序")


def cmd_delete(args, z):
    it = z.item(args.key)
    d = it["data"]
    kids = z.children(args.key)
    print("即将删除：%s | %s | 子项 %d 个" % (args.key, d.get("title"), len(kids)))
    print(">>> 注意：本机 API 的删除是【永久删除】，不进回收站，无法撤销 <<<")
    if not args.yes:
        sys.exit("已取消。确认无误请加 --yes")
    z.delete_item(args.key, dry_run=args.dry_run)
    print("   已删除")


# ----------------------------------------------------------------- 全库体检
# 附件标题的「无意义值」：Zotero 抓不到文献信息时会给附件起这些名字
_BAD_ATT_TITLES = {"", "pdf", "无标题", "untitled"}
# 「通用占位名」：合法但看不出是哪篇，属于可优化项
_GENERIC_ATT_TITLES = {"full text pdf", "fulltext pdf", "full-text pdf", "全文", "snapshot"}


def _norm_title(t):
    """题名归一化：只留字母数字与汉字，便于判重。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (t or "").lower())


def _brief(it, extra=""):
    d = it["data"]
    return {
        "key": it["key"],
        "type": d["itemType"],
        "title": (d.get("title") or "").strip() or "(空)",
        "dateAdded": d.get("dateAdded"),
        "collections": d.get("collections") or [],
        "extra": extra,
    }


def cmd_scan(args, z):
    """全库体检：只读，不修改任何东西。"""
    its = z.all_items(include_trashed=bool(args.trashed))
    if not args.trashed:
        its = [it for it in its if not it["data"].get("deleted")]

    kids = {}
    for it in its:
        p = it["data"].get("parentItem")
        if p:
            kids.setdefault(p, []).append(it)
    tops = [it for it in its if not it["data"].get("parentItem")
            and it["data"]["itemType"] not in ("attachment", "note")]
    atts = [it for it in its if it["data"]["itemType"] == "attachment"]

    report = {"empty_title": [], "null_att_title": [], "generic_att_title": [],
              "no_pdf": [], "missing_file": [], "uncategorized": []}

    for it in tops:
        if not (it["data"].get("title") or "").strip():
            report["empty_title"].append(_brief(it))

    for it in atts:
        d = it["data"]
        title = (d.get("title") or "").strip()
        fn = (d.get("filename") or "").strip()
        if title.lower() in _BAD_ATT_TITLES:
            report["null_att_title"].append(_brief(it, extra="filename=%s" % fn))
        elif title.lower() in _GENERIC_ATT_TITLES:
            report["generic_att_title"].append(_brief(it, extra="filename=%s" % fn))
        elif d.get("parentItem") and fn and title == os.path.splitext(fn)[0]:
            report["generic_att_title"].append(
                _brief(it, extra="标题=文件名（可改为论文真名）"))

    for it in tops:
        has_att = any(c["data"]["itemType"] == "attachment" for c in kids.get(it["key"], []))
        if not has_att:
            report["no_pdf"].append(_brief(it))

    for it in atts:
        d = it["data"]
        fn = d.get("filename")
        if d.get("linkMode") == "imported_file" and fn:
            if z.attachment_file_exists(it["key"], fn) is False:
                report["missing_file"].append(_brief(it, extra="filename=%s" % fn))

    for it in tops:
        if not (it["data"].get("collections") or []):
            report["uncategorized"].append(_brief(it))

    if args.json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    sections = [
        ("empty_title", "空标题题录（Zotero 列表里显示为 [类型名]）"),
        ("null_att_title", "附件标题是「PDF」/空（真问题：看不出是哪篇）"),
        ("generic_att_title", "附件标题是「Full Text PDF」或文件名（可优化为论文真名）"),
        ("no_pdf", "未挂 PDF 全文的题录"),
        ("missing_file", "附件文件缺失（库里有条目，storage 里没文件）"),
        ("uncategorized", "未归入任何分类的题录"),
    ]
    print("== 全库体检 ==（%s）" % ("含回收站" if args.trashed else "不含回收站"))
    print("   条目总数 %d | 题录 %d | 附件 %d" % (len(its), len(tops), len(atts)))
    total = 0
    for k, label in sections:
        rows = report[k]
        total += len(rows)
        print("\n【%s】%d 条" % (label, len(rows)))
        for r in rows[:args.limit]:
            print("   %-9s %-15s %s" % (r["key"], r["type"], r["title"][:54]))
            if r["extra"]:
                print("             %s" % r["extra"])
        if len(rows) > args.limit:
            print("   ... 其余 %d 条省略（用 --limit 调整）" % (len(rows) - args.limit))
    real_keys = ("empty_title", "null_att_title", "missing_file")
    n_real = sum(len(report[k]) for k in real_keys)
    n_tip = total - n_real
    print("\n== 合计：真问题 %d 处 ｜ 提示项 %d 处 ==" % (n_real, n_tip))
    if n_real:
        print("   真问题建议尽快处理；提示项不影响使用，可择机优化。")
    elif n_tip == 0:
        print("   库很干净，没发现问题。")


def _find_duplicates(z, loose=0, include_trashed=False):
    """按「DOI 相同」或「题名归一化相同（可截断到前 N 字符）」找重复题录。"""
    its = z.all_items(include_trashed=include_trashed)
    if not include_trashed:
        its = [it for it in its if not it["data"].get("deleted")]
    tops = [it for it in its if not it["data"].get("parentItem")
            and it["data"]["itemType"] not in ("attachment", "note")]
    kids = {}
    for it in its:
        p = it["data"].get("parentItem")
        if p:
            kids.setdefault(p, []).append(it)

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    buckets = {}
    for it in tops:
        k = it["key"]
        find(k)
        d = it["data"]
        doi = (d.get("DOI") or "").strip().lower()
        if doi:
            buckets.setdefault(("doi", doi), []).append(k)
        nt = _norm_title(d.get("title"))
        if nt:
            buckets.setdefault(("title", nt[:loose] if loose else nt), []).append(k)
    for ks in buckets.values():
        for k in ks[1:]:
            union(ks[0], k)

    groups = {}
    for it in tops:
        groups.setdefault(find(it["key"]), []).append(it)

    dups = []
    for g in groups.values():
        if len(g) < 2:
            continue
        # 建议保留：附件最多者优先；并列时取最早的 dateAdded（原始那条）
        def keep_rank(it):
            n_pdf = len([c for c in kids.get(it["key"], [])
                         if c["data"]["itemType"] == "attachment"])
            return (-n_pdf, it["data"].get("dateAdded") or "9999")
        ranked = sorted(g, key=keep_rank)
        dups.append({
            "keep": ranked[0]["key"],
            "items": [{
                "key": it["key"], "type": it["data"]["itemType"],
                "title": (it["data"].get("title") or "(空)"),
                "date": it["data"].get("date"), "DOI": it["data"].get("DOI") or "",
                "dateAdded": it["data"].get("dateAdded"),
                "collections": it["data"].get("collections") or [],
                "n_attachments": len([c for c in kids.get(it["key"], [])
                                      if c["data"]["itemType"] == "attachment"]),
                "n_notes": len([c for c in kids.get(it["key"], [])
                                if c["data"]["itemType"] == "note"]),
            } for it in ranked],
        })
    dups.sort(key=lambda x: -len(x["items"]))
    return dups


def cmd_dedupe(args, z):
    """查重复条目：**只报告，不删除**（删除交给用户确认后走 delete 子命令）。"""
    dups = _find_duplicates(z, loose=args.loose or 0)
    if args.json_out:
        print(json.dumps(dups, ensure_ascii=False, indent=2))
        return
    mode = "模糊匹配（题名前 %d 字符）" % args.loose if args.loose else "精确匹配（题名归一化后完全一致，或 DOI 相同）"
    print("== 查重结果 ==（%s）" % mode)
    if not dups:
        print("   没有发现重复题录。")
        return
    print("   发现 %d 组疑似重复，共涉及 %d 条题录\n"
          % (len(dups), sum(len(g["items"]) for g in dups)))
    for i, g in enumerate(dups, 1):
        print("【第 %d 组】%d 条" % (i, len(g["items"])))
        for it in g["items"]:
            mark = "✔建议保留" if it["key"] == g["keep"] else "  可删     "
            print("   %s %-9s %s" % (mark, it["key"], it["title"][:52]))
            print("              %s | PDF %d 笔记 %d | dateAdded %s | tags=%s"
                  % (it["date"] or "?", it["n_attachments"], it["n_notes"],
                     it["dateAdded"], it["collections"]))
        print()
    print(">>> 本命令不会删除任何东西。确认要删的 key 后，用：")
    print(">>>   python zotero_tool.py show <KEY>      # 先看清内容")
    print(">>>   python zotero_tool.py delete <KEY> --yes")


# --------------------------------------------------------------------- 入口
def build_parser():
    # --dry-run 放在公共父解析器里，命令前后都能写（未提供时不设属性，避免互相覆盖）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="只打印，不真正写入")

    p = argparse.ArgumentParser(description="本机 Zotero 文库工具", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", parents=[common])
    sub.add_parser("collections", parents=[common])

    s = sub.add_parser("list", parents=[common])
    s.add_argument("--collection")
    s.add_argument("--limit", type=int, default=100)

    s = sub.add_parser("show", parents=[common])
    s.add_argument("key")

    s = sub.add_parser("import-arxiv", parents=[common])
    s.add_argument("ids", nargs="+")
    s.add_argument("--collection")
    s.add_argument("--tag", action="append", default=[])
    s.add_argument("--pdf-dir")
    s.add_argument("--no-pdf", action="store_true")
    s.add_argument("--type", default="auto",
                   choices=["auto", "preprint", "conferencePaper", "journalArticle"],
                   help="条目类型；auto=按 arXiv 的 journal_ref/comment 推断"
                        "（注意该接口常常不返回这两项，会退回 preprint）")

    s = sub.add_parser("attach", parents=[common])
    s.add_argument("key")
    s.add_argument("pdf")
    s.add_argument("--title")

    s = sub.add_parser("note", parents=[common])
    s.add_argument("key")
    s.add_argument("--text")
    s.add_argument("--file")

    s = sub.add_parser("add-to-collection", parents=[common])
    s.add_argument("keys", nargs="+")
    s.add_argument("--collection", required=True)

    s = sub.add_parser("set-field", parents=[common])
    s.add_argument("key")
    s.add_argument("pairs", nargs="+")

    s = sub.add_parser("order", parents=[common])
    s.add_argument("keys", nargs="+")
    s.add_argument("--collection")
    s.add_argument("--base", help="基准时间，如 2026-10-12T13:00:03（默认当前 UTC）")

    s = sub.add_parser("scan", parents=[common], help="全库体检（只读）")
    s.add_argument("--limit", type=int, default=30, help="每类最多列几条，默认 30")
    s.add_argument("--trashed", action="store_true", help="连同回收站一起体检")
    s.add_argument("--json", dest="json_out", action="store_true", help="以 JSON 输出")

    s = sub.add_parser("dedupe", parents=[common], help="查重复条目（只报告）")
    s.add_argument("--loose", type=int, nargs="?", const=45, default=0,
                   help="模糊匹配：按题名前 N 字符归组（不写数字默认 45）；省略则不启用")
    s.add_argument("--json", dest="json_out", action="store_true", help="以 JSON 输出")

    s = sub.add_parser("delete", parents=[common])
    s.add_argument("key")
    s.add_argument("--yes", action="store_true")

    return p


def main():
    args = build_parser().parse_args()
    if not getattr(args, "dry_run", False):
        args.dry_run = False
    z = ZoteroClient(verbose=True)
    try:
        {
            "doctor": cmd_doctor, "collections": cmd_collections, "list": cmd_list,
            "show": cmd_show, "import-arxiv": cmd_import_arxiv, "attach": cmd_attach,
            "note": cmd_note, "add-to-collection": cmd_add_to_collection,
            "set-field": cmd_set_field, "order": cmd_order, "delete": cmd_delete,
            "scan": cmd_scan, "dedupe": cmd_dedupe,
        }[args.cmd](args, z)
    except ZoteroError as e:
        sys.exit("Zotero 接口报错：\n%s" % e)


if __name__ == "__main__":
    main()
