#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哔哩哔哩 iOS HAR 抓包分析工具

用途：从 Loon / Stream / Charles 导出的 HAR 里定位 B站广告，辅助维护 Loon 插件规则。

用法：
    python analyze_har.py <file.har>              # 总览
    python analyze_har.py <file.har> --check      # 先看 MITM 到底有没有生效
    python analyze_har.py <file.har> --hosts      # 请求域名排行
    python analyze_har.py <file.har> --splash     # 开屏广告专项（素材条数 / 体积 / 落地页）
    python analyze_har.py <file.har> --feed       # 信息流卡片逐条体检（标出广告卡）
    python analyze_har.py <file.har> --scan-ads   # 遍历 JSON 响应，定位广告字段路径
    python analyze_har.py <file.har> --all        # 全部

核心知识点（都是踩过的坑，改规则前先看一遍）：
    1. Loon 导出的 HAR 只包含「看得到完整内容」的请求。如果整份 HAR 里一条 https
       都没有、或者几乎没有响应体，说明 MITM 没解密 —— 此时插件里的 [Rewrite]
       一条都不会执行，分析广告字段没有任何意义。所以 --check 永远是第一步。
    2. B站的响应体在 HAR 里常带 "encoding": "base64"，不解码直接搜关键字会漏。
    3. 首页信息流的【正常直播卡】也带 ad_info 字段，但里面只有 is_ad_loc / resource，
       没有 is_ad、没有 creative_id。按 ad_info 是否存在来删会把正常内容删掉。
    4. 竖屏 story 的广告卡是 card_goto=vertical_ad_av，正常竖屏卡是 vertical_av。
    5. 开屏广告是四条接口（list / show / brand/list / event/list2），
       list 一次下发 80+ 条素材、2MB+，只拦 show 等于没拦。
"""

import argparse
import base64
import collections
import json
import re
import sys
import urllib.parse

# 广告 / 上报类域名
AD_HOST_PATTERN = re.compile(
    r"(^cm\.bilibili\.com$"
    r"|pangolin|pglstatp|ctobsnssdk|gromore|ugdtimg"
    r"|1rtb|tanx\.com|open\.snssdk\.com|adashx)",
    re.I,
)

# 埋点，不是广告但不干净
STATS_HOST_PATTERN = re.compile(r"^(data\.bilibili\.com|dataflow\.biliapi\.com)$", re.I)

# 业务主域：出现这些才说明抓到了真正的业务流量
BIZ_HOST_PATTERN = re.compile(
    r"(app\.bilibili\.com|api\.bilibili\.com|api\.live\.bilibili\.com|grpc\.biliapi\.net)",
    re.I,
)

# 广告接口路径（用于 --check 判断抓包是否覆盖到广告链路）
AD_PATH_PATTERN = re.compile(
    r"(/x/v2/splash/|/x/v2/feed/index|/cm/api/|ads/material/report|GetWidgetBannerList)",
    re.I,
)

# 「像广告」的键名
AD_KEY_PATTERN = re.compile(
    r"^(ad_info|ad_cb|ad_order_id|is_ad|creative_id|cm_mark|splash_id"
    r"|ad_livegame_info|activity_banner_info|banner_v2|activity_card_v1)$",
    re.I,
)

# 「像广告」的卡片类型
AD_CARD_PATTERN = re.compile(r"^(ad|ad_av|ad_web|ad_web_gif|vertical_ad_av|ad_player)", re.I)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["log"]["entries"]


def body_text(entry):
    """取出响应体文本，自动处理 base64。"""
    content = entry.get("response", {}).get("content") or {}
    text = content.get("text") or ""
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", "replace")
        except Exception:
            return ""
    return text


def body_json(entry):
    raw = body_text(entry)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def host_of(entry):
    try:
        return urllib.parse.urlparse(entry["request"]["url"]).hostname or ""
    except Exception:
        return ""


def path_of(entry):
    try:
        return urllib.parse.urlparse(entry["request"]["url"]).path
    except Exception:
        return ""


def walk_paths(obj, key, path="$", out=None, depth=0):
    """收集某个键在 JSON 里的所有路径，用于精确定位广告字段。"""
    if out is None:
        out = []
    if depth > 18:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = "%s.%s" % (path, k)
            if k == key:
                out.append(sub)
            walk_paths(v, key, sub, out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_paths(v, key, "%s[%d]" % (path, i), out, depth + 1)
    return out


def norm(path):
    return re.sub(r"\[\d+\]", "[]", path)


# ── 各检查项 ────────────────────────────────────────────────


def cmd_check(entries):
    total = len(entries)
    https = sum(1 for e in entries if e["request"]["url"].startswith("https"))
    with_body = sum(1 for e in entries if body_text(e))
    with_json = sum(1 for e in entries if body_json(e) is not None)
    biz = sum(1 for e in entries if BIZ_HOST_PATTERN.search(host_of(e)))
    ad = sum(1 for e in entries if AD_PATH_PATTERN.search(host_of(e) + path_of(e)))

    print("请求总数        : %d" % total)
    print("HTTPS           : %d" % https)
    print("有响应体        : %d" % with_body)
    print("可解析 JSON     : %d" % with_json)
    print("B站业务域名     : %d" % biz)
    print("命中的广告接口  : %d" % ad)
    print()

    ok = True
    if total == 0:
        print("❌ HAR 里没有任何请求，文件可能不是抓包导出")
        ok = False
    if https == 0:
        print("❌ 没有任何 HTTPS 请求 —— 抓包时走的是明文，或者规则没经过 Loon")
        ok = False
    if with_body == 0:
        print("❌ 所有请求都没有响应体 —— MITM 没解密，插件里的 [Rewrite] 一条都不会执行")
        ok = False
    elif with_json == 0:
        print("❌ 没有可解析的 JSON 响应 —— 同上，先解决 MITM")
        ok = False
    if ad == 0:
        print("⚠ 没有命中任何已知广告接口 —— 抓包期间可能没触发开屏/信息流，分析结果会不完整")
    if ok:
        print("✅ 抓包可用：HTTPS 已解密，可以做字段级分析")
    return ok


def cmd_hosts(entries):
    counter = collections.Counter(host_of(e) for e in entries)
    print("%-6s %s" % ("次数", "域名"))
    for host, count in counter.most_common(40):
        tag = ""
        if AD_HOST_PATTERN.search(host):
            tag = "  ← 广告/上报"
        elif STATS_HOST_PATTERN.search(host):
            tag = "  ← 埋点"
        print("%-6d %s%s" % (count, host, tag))


def cmd_splash(entries):
    found = False
    for e in entries:
        path = path_of(e)
        if not path.startswith("/x/v2/splash/"):
            continue
        found = True
        data = body_json(e) or {}
        payload = host_of(e) + path
        size = len(body_text(e))
        print("=" * 78)
        print("%s  HTTP %s  响应体 %d 字节 (%.1f MB)" % (
            payload, e["response"].get("status"), size, size / 1024 / 1024))
        d = data.get("data") or {}
        items = d.get("list") or []
        if items:
            print("  素材清单 %d 条" % len(items))
            for label, key in (("source", "source"), ("type", "type"), ("card_type", "card_type")):
                dist = collections.Counter(str(x.get(key)) for x in items)
                print("    %-10s %s" % (label + " 分布", dict(dist.most_common(6))))
            sample = items[0]
            print("    样例 id=%s 时长=%ss 落地页=%s" % (
                sample.get("id"), sample.get("duration"),
                str(sample.get("uri"))[:80]))
            hits = [u for u in (str(x.get("uri") or "") for x in items)
                    if re.search(r"(jd\.com|taobao|tmall|snssdk|bytedance|pinduoduo|kuaishou)", u)]
            if hits:
                print("    含第三方落地页 %d 条，例如：%s" % (len(hits), hits[0][:100]))
        show = d.get("show") or []
        if show:
            print("  今日展示队列 %d 条（带 ad_cb 回执）" % len(show))
        if not items and not show:
            print("  无 list / show 字段（该接口本身可能只返回事件配置，或已被插件 reject-dict 清空）")
    if not found:
        print("抓包里没有 /x/v2/splash/* 请求。开屏广告只在冷启动时请求，")
        print("抓包前请先彻底杀掉 App 再录。")


def cmd_feed(entries):
    found = False
    for e in entries:
        path = path_of(e)
        if "feed/index" not in path:
            continue
        data = body_json(e)
        if not data:
            continue
        items = (data.get("data") or {}).get("items")
        if not isinstance(items, list):
            continue
        found = True
        print("=" * 78)
        print("%s%s  共 %d 张卡" % (host_of(e), path, len(items)))
        ads = 0
        for i, it in enumerate(items):
            ad_info = it.get("ad_info") or {}
            real_ad = (
                it.get("is_ad") is True
                or ad_info.get("is_ad") is True
                or (ad_info.get("creative_id") or 0) > 0
                or bool(AD_CARD_PATTERN.search(str(it.get("card_goto") or "")))
            )
            if real_ad:
                ads += 1
            mark = "🚫 广告" if real_ad else ("  正常" if not ad_info else "  正常(带 ad_info)")
            print("  [%2d] %s  card_type=%-16s card_goto=%-16s %s" % (
                i, mark, it.get("card_type"), it.get("card_goto"),
                str(it.get("title") or "")[:28]))
        print("  → 广告卡 %d / %d" % (ads, len(items)))
    if not found:
        print("抓包里没有带 items 的 feed/index 响应。信息流广告要多刷几次首页才会出现。")


def cmd_scan_ads(entries):
    print("%-46s %-28s %s" % ("接口", "广告字段", "出现次数"))
    print("-" * 96)
    seen = collections.Counter()
    for e in entries:
        data = body_json(e)
        if data is None:
            continue
        key = host_of(e) + path_of(e)
        hits = collections.Counter()
        for probe in ("ad_info", "is_ad", "creative_id", "ad_cb", "ad_order_id",
                      "cm_mark", "splash_id", "ad_livegame_info", "activity_banner_info"):
            paths = walk_paths(data, probe)
            if paths:
                hits[probe + " → " + sorted({norm(p) for p in paths})[0]] = len(paths)
        for k, v in hits.items():
            seen[(key, k)] += v
    for (key, field), count in sorted(seen.items(), key=lambda x: -x[1])[:40]:
        print("%-46s %-28s %d" % (key[:46], field[:28], count))
    if not seen:
        print("没有命中任何广告字段。要么抓包没覆盖广告链路，要么 MITM 没生效（先跑 --check）。")


def cmd_hosts_ads(entries):
    counter = collections.Counter(
        host_of(e) for e in entries if AD_HOST_PATTERN.search(host_of(e)))
    if not counter:
        print("没有命中已知广告域名。B站的广告主要靠接口下发，不靠第三方 SDK 域名。")
        return
    for host, count in counter.most_common():
        print("%-5d %s" % (count, host))


def main():
    parser = argparse.ArgumentParser(
        description="哔哩哔哩 iOS HAR 抓包分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="建议顺序：--check → --hosts → --splash / --feed → --scan-ads")
    parser.add_argument("har", help="HAR 文件路径")
    parser.add_argument("--check", action="store_true", help="验证 MITM 是否生效（先跑这个）")
    parser.add_argument("--hosts", action="store_true", help="域名排行")
    parser.add_argument("--splash", action="store_true", help="开屏广告专项")
    parser.add_argument("--feed", action="store_true", help="信息流卡片逐条体检")
    parser.add_argument("--scan-ads", action="store_true", help="定位广告字段路径")
    parser.add_argument("--ads", action="store_true", help="只看广告域名")
    parser.add_argument("--all", action="store_true", help="全部检查")
    args = parser.parse_args()

    entries = load(args.har)
    if not any([args.check, args.hosts, args.splash, args.feed,
                args.scan_ads, args.ads, args.all]):
        print("请求总数: %d\n" % len(entries))
        cmd_check(entries)
        print("\n【域名排行】")
        cmd_hosts(entries)
        print("\n提示：--check / --splash / --feed / --scan-ads 可单独跑，--all 跑全部")
        return

    if args.all or args.check:
        cmd_check(entries)
        print()
    if args.all or args.hosts:
        cmd_hosts(entries)
        print()
    if args.all or args.splash:
        cmd_splash(entries)
        print()
    if args.all or args.feed:
        cmd_feed(entries)
        print()
    if args.all or args.ads:
        cmd_hosts_ads(entries)
        print()
    if args.all or args.scan_ads:
        cmd_scan_ads(entries)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print("找不到文件：%s" % sys.argv[1])
        sys.exit(1)
