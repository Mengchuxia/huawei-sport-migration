#!/usr/bin/env python3
"""核验：华为服务端到底有哪些记录，缺什么、重复了什么。

    python scripts/huawei_verify.py --fit-dir out --workouts workouts.json

以服务端活动记录为准，不看页面弹窗、不看页面内的历史列表（后者是当前会话缓存，
重新登录就会清空，不能作为依据）。

比对键是「开始时间（分钟）+ 时长（秒）」：同一分钟的两场不同运动不会被误判成重复，
平台侧 1 秒取整差则由 5 秒容差兜底。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import hw_common as hw


def main() -> int:
    ap = argparse.ArgumentParser(description="核验华为服务端导入结果")
    ap.add_argument("--fit-dir", default="out")
    ap.add_argument("--workouts", default="workouts.json")
    ap.add_argument("--since", default="",
                    help="服务端记录查询起点（YYYY-MM-DD），留空按最早一条运动自动推算")
    ap.add_argument("--report", default="verify-report.md")
    ap.add_argument("--json", default="verify-report.json")
    args = ap.parse_args()

    fit_dir = Path(args.fit_dir).expanduser()
    files = sorted(fit_dir.glob("*.fit"))
    if not files:
        raise SystemExit(f"{fit_dir} 里没有 .fit 文件")

    from fit_encode import file_name, parse_time

    source_path = Path(args.workouts).expanduser()
    expected: list[dict] = []
    if source_path.is_file():
        data = json.loads(source_path.read_text(encoding="utf-8"))
        items = data["workouts"] if isinstance(data, dict) else data
        for item in items:
            start = parse_time(item["start_time"])
            elapsed = float(item.get("elapsed_s") or item.get("duration_s") or 0)
            expected.append({
                "start": int(start), "elapsed_s": elapsed,
                "key": hw.match_key(start, elapsed),
                "file": file_name(item), "sport": item.get("sport"),
            })
    else:
        for path in files:
            identity = hw.fit_identity(path)
            if identity is None:
                start, elapsed = None, 0.0
                parts = path.stem.split("_")
                key = "_".join(parts[:2]) if len(parts) >= 2 else path.stem
            else:
                start, elapsed = identity[0], identity[1]
                key = hw.match_key(start, elapsed)
            expected.append({"start": start, "elapsed_s": elapsed,
                             "key": key, "file": path.name, "sport": None})

    since = args.since
    if not since:
        stamps = [item["start"] for item in expected if item.get("start")]
        if stamps:
            since = (datetime.fromtimestamp(min(stamps)) - timedelta(days=2)).strftime("%Y-%m-%d")
        else:
            since = "2015-01-01"

    sync = hw.require_playwright()
    with sync() as pw:
        context, page = hw.launch(pw)
        try:
            hw.open_import_page(page)
            activities = hw.fetch_activities(page, since)
        finally:
            context.close()

    index = hw.RecordIndex(activities)
    missing, duplicated, diff_duration, uncertain = [], [], [], []
    matched_ids: set = set()
    for item in expected:
        if item.get("start") is None:
            uncertain.append(item)  # 读不出开始时间，无法判断入库与否
            continue
        found, unsure = index.find(item["start"], item["elapsed_s"])
        if not found:
            if unsure:
                uncertain.append(item)
            else:
                missing.append(item)
            continue
        for record in found:
            matched_ids.add(record.get("id") if record.get("id") is not None else id(record))
        if len(found) > 1:
            duplicated.append({"key": item["key"], "count": len(found), "file": item["file"]})
        elif item["elapsed_s"]:
            span = hw.span_of(found[0]) or 0
            if abs(span - item["elapsed_s"]) > 5:
                diff_duration.append({"key": item["key"], "file": item["file"],
                                      "source_s": item["elapsed_s"], "server_s": round(span, 1)})

    extras: dict[str, int] = {}
    for activity in activities:
        activity_id = activity.get("id") if activity.get("id") is not None else id(activity)
        if activity_id in matched_ids:
            continue
        key = activity.get("key") or "?"
        extras[key] = extras.get(key, 0) + 1
    extras = [{"key": key, "count": count} for key, count in sorted(extras.items())]

    landed = len(expected) - len(missing) - len(uncertain)
    lines = [
        "# 华为导入核验报告",
        "",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        "",
        "| 项目 | 数量 |",
        "|---|---|",
        f"| 本地待导入 | {len(expected)} |",
        f"| 服务端记录 | {len(activities)} |",
        f"| 已入库 | {landed} |",
        f"| 缺失 | {len(missing)} |",
        f"| 重复（同一分钟同一时长多条） | {len(duplicated)} |",
        f"| 时长不一致 | {len(diff_duration)} |",
        f"| 无法确认 | {len(uncertain)} |",
        "",
    ]
    if missing:
        lines += ["## 缺失（服务端没有对应记录）", "", "| 开始时间 | 文件 |", "|---|---|"]
        lines += [f"| {m['key']} | {m['file']} |" for m in missing]
        lines.append("")
    if duplicated:
        lines += ["## 重复（同一分钟同一时长多条记录）", "", "| 比对键 | 条数 | 文件 |", "|---|---|---|"]
        lines += [f"| {d['key']} | {d['count']} | {d['file']} |" for d in duplicated]
        lines.append("")
    if diff_duration:
        lines += ["## 时长不一致", "", "| 比对键 | 文件 | 源(s) | 服务端(s) |", "|---|---|---|---|"]
        lines += [f"| {d['key']} | {d['file']} | {d['source_s']:.0f} | {d['server_s']:.0f} |"
                  for d in diff_duration]
        lines.append("")
    if uncertain:
        lines += ["## 无法确认（同一分钟已有多条记录，且时长都对不上）", "",
                  "| 比对键 | 文件 |", "|---|---|"]
        lines += [f"| {u['key']} | {u['file']} |" for u in uncertain]
        lines.append("")
    if extras:
        lines += ["## 服务端多出的记录（本地清单里没有，可能是其他来源或探针）", "",
                  "| 开始时间 | 条数 |", "|---|---|"]
        lines += [f"| {e['key']} | {e['count']} |" for e in extras]
        lines.append("")

    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    Path(args.json).write_text(json.dumps(
        {"expected": len(expected), "server": len(activities), "missing": missing,
         "duplicates": duplicated, "duration_mismatch": diff_duration,
         "uncertain": uncertain, "extras": extras},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"· 本地 {len(expected)} 条，服务端 {len(activities)} 条")
    print(f"· 已入库 {landed}，缺失 {len(missing)}，重复 {len(duplicated)}，"
          f"时长不一致 {len(diff_duration)}，无法确认 {len(uncertain)}")
    print(f"· 报告：{args.report}")
    return 1 if (missing or duplicated or diff_duration or uncertain) else 0


if __name__ == "__main__":
    sys.exit(main())
