#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
library.json 校验工具（资料库数据体检）

用法：
    python tools/check_library.py
    python tools/check_library.py site/data/library.json
    python tools/check_library.py 路径/library.json --html 路径/index.html

退出码：0 = 通过（可能有提醒）  1 = 有错误，建议先修再提交

只依赖标准库，Python 3.8+ 可直接跑，不需要装任何东西。
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 常量

SECTIONS = {
    "articles": "公众号长文",
    "records": "大会录屏",
    "planet": "星球精华",
    "live": "直播回放",
    "docs": "工具文档",
}

GROUP_TYPES = {"list", "grid", "details"}
ITEM_KEYS = {"title", "url", "tag", "src", "code", "date", "isNew"}
MAX_TITLE = 46          # 超过这个长度，列表行会折行或截断
CODE_RE = re.compile(r"^[A-Za-z0-9]{4}$")


# ---------------------------------------------------------------- 读取

def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def read_html(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def html_groups(html):
    """从 index.html 抽出 {section_id: {"groups": [...], "items": n, "grid": bool, "details": bool}}"""
    out = {}
    if not html:
        return out
    for sid in SECTIONS:
        m = re.search(r'<section[^>]*id="%s"' % sid, html)
        if not m:
            continue
        nxt = re.search(r'<section class="section[^"]*" id=', html[m.end():])
        seg = html[m.end(): m.end() + nxt.start()] if nxt else html[m.end():]
        # 两种分组头写法：普通分区 <div class="group-head">，文档区 <div class="gh">
        heads = re.findall(r'<div class="(?:group-head|gh)">.*?<h3>(.*?)</h3>', seg, re.S)
        out[sid] = {
            "groups": [re.sub(r"\s+", " ", g).strip() for g in heads],
            "items": seg.count("data-item"),
            "grid": 'class="pgrid"' in seg,
            "details": "<details" in seg,
        }
    return out


# ---------------------------------------------------------------- 校验

class Report:
    def __init__(self):
        self.errors = []
        self.warns = []

    def err(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))


def validate(data, html_map, report):
    stats = []  # (章节名, 条目数, 分组数, 声明tag)

    if not isinstance(data, dict):
        report.err("根", "最外层必须是一个对象（以 { 开头、} 结尾）")
        return stats

    if not data.get("version"):
        report.warn("根", "缺少 version 字段（建议写成日期，如 2026-11-19，便于确认改到哪一版）")

    sections = data.get("sections")
    if not isinstance(sections, dict):
        report.err("sections", "缺少 sections，或它不是对象")
        return stats

    for sid in sections:
        if sid not in SECTIONS:
            report.err(f"sections.{sid}",
                       f"未知章节名「{sid}」。只能是 {'、'.join(SECTIONS)}，写错这一整章节不会显示")

    seen_urls = {}
    for sid, meta in sections.items():
        if not isinstance(meta, dict):
            report.err(f"sections.{sid}", "这个章节必须是对象 { tag, groups }")
            continue

        label = SECTIONS.get(sid, sid)
        tag = meta.get("tag")
        if not tag:
            report.warn(f"sections.{sid}", "缺少 tag（区块右上角的「61 篇」那类标签）")

        groups = meta.get("groups")
        if not isinstance(groups, list) or not groups:
            report.err(f"sections.{sid}", "groups 为空，这个章节会没有内容")
            continue

        total_items = 0
        heads = []
        hmap = html_map.get(sid)

        for gi, g in enumerate(groups):
            where = f"sections.{sid}.groups[{gi}]"
            if not isinstance(g, dict):
                report.err(where, "分组必须是对象")
                continue

            head = (g.get("head") or "").strip()
            gtype = (g.get("type") or "list").strip()
            items = g.get("items")

            if not head:
                report.err(where, "缺少 head（分组标题）")
            if gtype not in GROUP_TYPES:
                report.err(where, f'type 只能是 list / grid / details，当前是「{gtype}」')
            if not isinstance(items, list) or not items:
                report.err(where, f"「{head}」的 items 为空")
                continue

            heads.append(head)

            # 分组名必须和页面上的标题完全一致，否则这一组不会渲染
            if hmap is not None and gtype == "list":
                if head not in hmap["groups"]:
                    report.err(
                        f"{where}（{head}）",
                        "页面里找不到同名分组，这一组的条目不会显示。"
                        f"当前页面上的分组是：{'、'.join(hmap['groups']) or '（空）'}"
                    )
            if gtype == "grid" and hmap is not None and not hmap["grid"]:
                report.err(f"{where}（{head}）", "页面里没有 .pgrid 网格容器，grid 组不会显示")
            if gtype == "details" and hmap is not None and not hmap["details"]:
                report.err(f"{where}（{head}）", "页面里没有折叠区 <details>，details 组不会显示")

            extra = g.get("extra") or 0
            if extra and gtype == "list" and head == "星友实操长文 · 近两个月":
                pass  # 该组的折叠区条数，属正常配置
            want = len(items) + (extra if isinstance(extra, int) else 0)
            cnt = g.get("count")
            if isinstance(cnt, str):
                m = re.match(r"\s*(\d+)", cnt)
                if m and int(m.group(1)) != want:
                    report.warn(f"{where}（{head}）",
                                f'count 写的是 {cnt}，按条目数应为 {want}（页面会自动纠正，不影响显示）')

            for ii, it in enumerate(items):
                iw = f"{where}.items[{ii}]"
                if not isinstance(it, dict):
                    report.err(iw, "条目必须是对象")
                    continue

                title = (it.get("title") or "").strip()
                url = (it.get("url") or "").strip()

                if not title:
                    report.err(iw, "缺少 title，列表里会是一条空白")
                elif len(title) > MAX_TITLE:
                    report.warn(iw, f"标题 {len(title)} 字，超过 {MAX_TITLE} 字在手机上会折行：「{title[:20]}…」")

                if not url:
                    report.err(iw + (f"（{title[:16]}）" if title else ""), "缺少 url，点了打不开")
                elif " " in url or "\u3000" in url:
                    report.err(iw, f"url 里有空格，链接会失效：「{url[:40]}」")
                elif not re.match(r"^https?://", url):
                    # 站内相对路径（如 planet/p123.html）是正常的
                    if url.startswith(("/", "./", "../", "#", "planet/", "assets/")):
                        pass
                    elif re.search(r"\.(com|cn|net|org|io|me|cc|link)(/|$|\?)", url):
                        report.err(iw, f"网址少了 https://，浏览器会当成站内路径：「{url[:40]}」")
                    else:
                        report.warn(iw, f"不是完整网址，也不是已知的站内路径，确认一下：「{url[:40]}」")
                else:
                    key = url.rstrip("/")
                    if key in seen_urls and seen_urls[key] != title:
                        report.warn(iw, f"与「{seen_urls[key][:20]}」用了同一个链接")
                    else:
                        seen_urls[key] = title

                code = it.get("code")
                if code is not None:
                    code = str(code).strip()
                    if not CODE_RE.match(code):
                        report.warn(iw, f'提取码「{code}」不是 4 位字母数字，确认一下（按钮上会原样显示）')

                for k, v in it.items():
                    if k not in ITEM_KEYS:
                        report.warn(iw, f"多余字段「{k}」，页面不读它，可能是拼写错了（title/url/tag/src/code/date/isNew）")
                    elif k == "isNew":
                        if not isinstance(v, bool):
                            report.warn(iw, "isNew 要写 true 或 false（不加引号）")
                    elif v is not None and not isinstance(v, str):
                        report.warn(iw, f"字段「{k}」建议写成字符串")

                total_items += 1

        # 同章节内重名
        dup = {h for h in heads if heads.count(h) > 1}
        for h in dup:
            report.warn(f"sections.{sid}", f"分组名「{h}」出现了不止一次，只会渲染最后匹配到的那个")

        # 章节条目总数 vs 页面内置条数
        if hmap is not None and all(
            (g.get("type") or "list") == "list" for g in groups if isinstance(g, dict)
        ) and hmap["items"] and hmap["items"] != total_items:
            report.warn(
                f"sections.{sid}",
                f"数据里 {total_items} 条，页面内置 {hmap['items']} 条（不一致不影响显示，"
                f"会以数据为准；除非页面里还手工放了一张卡片）"
            )

        stats.append((label, total_items, len(groups), tag or "—"))

    return stats


# ---------------------------------------------------------------- 输出

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    cwd = os.getcwd()

    ap = argparse.ArgumentParser(add_help=True, description="校验 library.json")
    ap.add_argument("file", nargs="?", default=None, help="library.json 路径")
    ap.add_argument("--html", default=None, help="index.html 路径（用于核对分组名）")
    args = ap.parse_args()

    # 数据文件：显式传入 > 脚本同目录 > 项目里的 site/data/library.json > 当前目录
    path = args.file
    if not path:
        for c in (os.path.join(here, "library.json"),
                  os.path.join(root, "site", "data", "library.json"),
                  os.path.join(cwd, "library.json"),
                  os.path.join(cwd, "data", "library.json")):
            if os.path.exists(c):
                path = c
                break
    if not path or not os.path.exists(path):
        print(f"✗ 找不到文件：{path or '（自动查找失败，请直接指定路径）'}")
        return 2

    # 页面文件：显式传入 > 数据目录的上两级 index.html > 项目里的 site/index.html
    html_path = args.html
    if not html_path:
        for c in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "index.html"),
                  os.path.join(root, "site", "index.html"),
                  os.path.join(cwd, "site", "index.html")):
            if os.path.exists(c):
                html_path = c
                break

    print("资料库数据校验")
    print(f"  数据：{path}")
    print(f"  页面：{html_path or '（未提供，跳过分组名核对）'}")
    print()

    try:
        data = read_json(path)
    except json.JSONDecodeError as e:
        print(f"✗ JSON 语法错误：第 {e.lineno} 行 第 {e.colno} 列")
        print(f"   {e.msg}")
        print("\n   常见原因：最后一条后面多了逗号、用了中文引号“”、少了一个 } 或 ]、")
        print("            网址里的 & 被写成了全角＆、复制时把说明文字也带进去了。")
        print("\n   ⚠ 语法错误时页面会自动回落到旧数据（不会白屏），但你的改动不会生效。")
        return 1

    report = Report()
    stats = validate(data, html_groups(read_html(html_path)), report)

    print("章节                        条目   分组   声明标签")
    print("─" * 52)
    for label, n, g, tag in stats:
        print(f"{label:<22}{n:>6}{g:>6}   {tag}")
    print("─" * 52)
    print(f"{'合计':<22}{sum(s[1] for s in stats):>6}")
    print()

    if report.errors:
        print(f"✗ 错误 {len(report.errors)} 个（这些问题会让条目显示不出来）")
        for i, (where, msg) in enumerate(report.errors, 1):
            print(f"  {i}. {where}")
            print(f"     {msg}")
        print()

    if report.warns:
        print(f"! 提醒 {len(report.warns)} 个（不影响显示，建议顺手看看）")
        for i, (where, msg) in enumerate(report.warns, 1):
            print(f"  {i}. {where}")
            print(f"     {msg}")
        print()

    if report.errors:
        print("结论：有错误，先修完再提交。")
        return 1

    print("结论：✓ 通过" + ("（有提醒，可忽略）" if report.warns else "，可以提交了。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
