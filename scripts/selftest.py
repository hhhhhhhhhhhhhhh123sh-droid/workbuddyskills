# -*- coding: utf-8 -*-
"""
selftest.py —— 环境写入能力自检。

默认只做**可逆**检查（建一个临时分类再删掉），不会动你的文献。
加上 `--with-pdf <某个PDF路径>` 才会额外测「给条目挂 PDF」的完整三步，
届时会临时建一条 `_技能自检_临时条目` 并挂上该 PDF，**跑完自动删除**。

用法：
    python selftest.py
    python selftest.py --with-pdf "D:/some/paper.pdf"
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zotero_client import ZoteroClient  # noqa: E402

TMP_COLL = "_技能自检_临时分类"
TMP_ITEM_TITLE = "_技能自检_临时条目"

z = ZoteroClient(verbose=True)
ap = argparse.ArgumentParser()
ap.add_argument("--with-pdf", help="额外测试 PDF 上传（传入一个存在的 PDF 路径）")
ap.add_argument("--keep", action="store_true", help="不清理临时对象（排错用）")
args = ap.parse_args()

ok = True

# ---- 1. 分类增删（可逆） ----
print("== 1. 分类增删 ==")
try:
    old = z.find_collection(TMP_COLL)
    if old:
        z.delete_collection(old)
    k = z.create_collection(TMP_COLL)
    print("   建分类  ->", k)
    assert z.find_collection(TMP_COLL) == k, "建完查不到"
    z.delete_collection(k)
    print("   删分类  -> ok")
    print("   剩余分类:", [c["data"]["name"] for c in z.collections()])
except Exception as e:
    ok = False
    print("   [失败]", e)

# ---- 2. 附件上传（可选） ----
if args.with_pdf:
    print("== 2. PDF 上传（完整三步） ==")
    item_key = att_key = None
    storage = None
    try:
        item_key = z.create_items([{
            "itemType": "preprint", "title": TMP_ITEM_TITLE,
            "creators": [], "tags": [], "collections": [], "relations": {},
        }])[0]
        print("   临时条目 ->", item_key)
        att_key = z.attach_pdf(item_key, args.with_pdf, title="自检附件")
        att = z.item(att_key)["data"]
        print("   附件字段: filename=%r linkMode=%s parent=%s" % (
            att.get("filename"), att.get("linkMode"), att.get("parentItem")))
        storage = os.path.join(z.find_data_dir(), "storage", att_key)
        files = os.listdir(storage) if os.path.isdir(storage) else []
        print("   落盘 %s -> %s" % (storage, files))
        if not files:
            ok = False
            print("   [失败] 文件没落盘")
    except Exception as e:
        ok = False
        print("   [失败]", e)
    finally:
        if not args.keep:
            print("== 3. 清理临时对象 ==")
            for k in (att_key, item_key):
                if k:
                    try:
                        z.delete_item(k)
                        print("   已删", k)
                    except Exception as e:
                        print("   [删除失败]", k, e)
            if storage and os.path.isdir(storage):
                shutil.rmtree(storage, ignore_errors=True)
                print("   已清理 storage:", storage)
        else:
            print("== 3. 已保留临时对象（--keep）: %s / %s ==" % (item_key, att_key))

print("\n== 自检结果:", "全部通过" if ok else "有失败项，请看上面日志", "==")
sys.exit(0 if ok else 1)
