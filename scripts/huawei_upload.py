#!/usr/bin/env python3
"""把 FIT 文件批量导入华为运动健康，并且只导「服务端还没有的」。

    python scripts/huawei_upload.py --fit-dir out --workouts workouts.json --dry-run
    python scripts/huawei_upload.py --fit-dir out --workouts workouts.json
    python scripts/huawei_upload.py --login-only

安全设计：
- 先查服务端已有哪些记录，再决定传什么；重复运行不会产生重复记录
- 比对键是「开始时间（分钟）+ 时长（秒）」，同分钟的两场不同运动不会被当成一条
- 每个文件只提交一次，失败不自动重传；以服务端结果为准
- 遇到验证码、风控或登录失效立即停止
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import hw_common as hw
from fit_encode import file_name, parse_time

RISK_WORDS = ("验证码", "安全验证", "操作过于频繁", "请稍后再试")


def load_sources(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["workouts"] if isinstance(data, dict) else data
    return {file_name(item): item for item in items}


def resolve_since(sources: dict, given: str) -> str:
    """没指定起点时，从最早一条运动的日期往前推两天，避免漏查旧记录。"""
    if given:
        return given
    stamps = []
    for item in sources.values():
        try:
            stamps.append(parse_time(item["start_time"]))
        except (KeyError, ValueError, TypeError):
            continue
    if not stamps:
        return "2015-01-01"
    return (datetime.fromtimestamp(min(stamps)) - timedelta(days=2)).strftime("%Y-%m-%d")


def identity_of(path: Path, sources: dict) -> tuple[int, float] | None:
    """优先用 workouts.json 里的源数据，没有就回读 FIT 自身。

    探针、手工放进目录的文件都不在源清单里，回读 FIT 才能判断它是不是已经入库。
    """
    source = sources.get(path.name)
    if source:
        try:
            start = parse_time(source["start_time"])
        except (KeyError, ValueError, TypeError):
            start = None
        if start is not None:
            elapsed = source.get("elapsed_s") or source.get("duration_s") or 0
            return int(start), float(elapsed)
    got = hw.fit_identity(path)
    if got is None:
        return None
    return got[0], got[1]


def main() -> int:
    ap = argparse.ArgumentParser(description="FIT 批量导入华为运动健康")
    ap.add_argument("--fit-dir", default="out")
    ap.add_argument("--workouts", default="workouts.json")
    ap.add_argument("--state", default=str(hw.STATE_DIR / "upload-state.json"))
    ap.add_argument("--batch", type=int, default=10, help="每批文件数，上限 50")
    ap.add_argument("--since", default="",
                    help="服务端记录查询起点（YYYY-MM-DD），留空按最早一条运动自动推算")
    ap.add_argument("--delay", type=float, default=2.5, help="批次之间的间隔秒数")
    ap.add_argument("--dry-run", action="store_true", help="只列清单；仍需登录一次以读取服务端记录")
    ap.add_argument("--login-only", action="store_true", help="只完成登录并保存登录态，不上传")
    args = ap.parse_args()

    sync = hw.require_playwright()

    if args.login_only:
        with sync() as pw:
            context, page = hw.launch(pw)
            try:
                hw.open_import_page(page)
            finally:
                context.close()
        print("· 登录态已保存，可以开始导入")
        return 0

    fit_dir = Path(args.fit_dir).expanduser()
    files = sorted(fit_dir.glob("*.fit"))
    if not files:
        raise SystemExit(f"{fit_dir} 里没有 .fit 文件")
    sources = load_sources(Path(args.workouts).expanduser())
    if not sources:
        raise SystemExit(
            f"缺少 {args.workouts}：没有它就无法判断哪些记录已经导入，继续跑可能产生重复记录。\n"
            "先用 convert.py / from_bridge.py 生成，或显式传入 --workouts <文件>。")
    since = resolve_since(sources, args.since)
    state_path = Path(args.state).expanduser()
    state = hw.load_state(state_path)
    done = set(state.get("uploaded") or [])

    with sync() as pw:
        context, page = hw.launch(pw)
        try:
            hw.open_import_page(page)
            activities = hw.fetch_activities(page, since)
            index = hw.RecordIndex(activities)
            print(f"· 服务端已有 {len(activities)} 条记录（查询起点 {since}）")

            plan: list[Path] = []
            skipped, unidentified, ambiguous = 0, [], []
            for path in files:
                identity = identity_of(path, sources)
                if identity is None:
                    unidentified.append(path.name)
                    continue
                found, unsure = index.find(*identity)
                if unsure:
                    ambiguous.append(path.name)
                    skipped += 1
                    continue
                if found or path.name in done:
                    skipped += 1
                    continue
                plan.append(path)

            print(f"· 待导入 {len(plan)} 个（已存在或已完成 {skipped} 个）")
            for name in unidentified:
                print(f"  ! 读不出开始时间，已跳过（不会盲传）：{name}")
            for name in ambiguous:
                print(f"  ! 同一分钟已有多条记录且时长对不上，为避免重复已跳过：{name}")
            for path in plan:
                print(f"    {path.name}")
            if args.dry_run:
                print("· 预演结束，没有上传任何文件")
                return 0
            if not plan:
                print("· 没有需要导入的文件")
                return 0

            batch_size = max(1, min(50, args.batch))
            uploaded = 0
            failures: list[dict] = []
            for batch_no, offset in enumerate(range(0, len(plan), batch_size), start=1):
                chunk = plan[offset: offset + batch_size]
                print(f"[{batch_no}] 上传 {len(chunk)} 个文件…")
                result = hw.upload_batch(page, chunk)
                text = result.get("dialog") or ""
                print(f"    → {text[:150] or '（没有读到结果弹窗）'}")
                if any(word in text for word in RISK_WORDS):
                    print("· 触发风控提示，已停止。请稍后在浏览器里手动处理。")
                    failures.append({"files": [p.name for p in chunk], "reason": "风控"})
                    break

                time.sleep(args.delay)
                after = hw.RecordIndex(hw.fetch_activities(page, since))

                for path in chunk:
                    identity = identity_of(path, sources)
                    found, unsure = after.find(*identity) if identity else ([], False)
                    if found:
                        done.add(path.name)
                        uploaded += 1
                        print(f"      ✓ {path.name} 已入库")
                    elif unsure:
                        failures.append({"file": path.name,
                                         "reason": "同一分钟已有多条记录，无法确认是否入库"})
                        print(f"      ? {path.name} 同一分钟已有多条记录，无法确认")
                    else:
                        failures.append({"file": path.name, "reason": text or "服务端未出现记录"})
                        print(f"      × {path.name} 服务端没有出现记录")
                state["uploaded"] = sorted(done)
                state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                hw.save_state(state_path, state)

            print(f"\n· 本次入库 {uploaded} 个，失败 {len(failures)} 个")
            for item in failures:
                print(f"    {item.get('file') or item.get('files')}: {item['reason'][:80]}")
            if failures:
                print("· 失败项不要直接重跑：先看 references/troubleshooting.md 定位原因。")
                return 1
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    sys.exit(main())
