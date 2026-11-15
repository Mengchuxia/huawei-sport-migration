#!/usr/bin/env python3
"""编码后自检：结构是否合规、数值是否与源数据一致。

    python scripts/fit_audit.py --fit-dir out --workouts workouts.json
    python scripts/fit_audit.py --fit-dir out --workouts workouts.json --report audit.json

检查项对应 references/fit-encoding.md 的规则，任何一项不过都不要上传。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z，FIT date_time / local_timestamp 的起点
REQUIRED = ("file_id_mesgs", "device_info_mesgs", "sport_mesgs", "event_mesgs",
            "record_mesgs", "session_mesgs", "activity_mesgs")


def epoch(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def audit_file(path: Path, source: dict | None) -> dict:
    from garmin_fit_sdk import Decoder, Stream

    problems: list[str] = []
    warnings: list[str] = []
    size = path.stat().st_size
    if size > MAX_BYTES:
        problems.append(f"文件 {size / 1024 / 1024:.2f} MB 超过 5 MB 上限")

    messages, errors = Decoder(Stream.from_file(str(path))).read()
    if errors:
        problems.append(f"解码报错：{errors[0]}")
    for key in REQUIRED:
        if not messages.get(key):
            problems.append(f"缺少必需消息 {key[:-6]}")
    sessions = messages.get("session_mesgs") or []
    if not sessions:
        return {"file": path.name, "problems": problems, "warnings": warnings}
    session = sessions[0]
    records = messages.get("record_mesgs") or []
    laps = messages.get("lap_mesgs") or []

    start = epoch(session.get("start_time"))
    end = epoch(session.get("timestamp"))
    elapsed = float(session.get("total_elapsed_time") or 0)
    timer = float(session.get("total_timer_time") or 0)
    distance = float(session.get("total_distance") or 0)

    if start is None or end is None:
        problems.append("session 缺 start_time 或 timestamp")
    elif elapsed and abs((end - start) - elapsed) > 2:
        problems.append(f"总时长与时间戳跨度不一致：{elapsed:.0f}s vs {end - start}s")
    if timer and elapsed and timer - elapsed > 1:
        problems.append(f"有效时长 {timer:.0f}s 大于总时长 {elapsed:.0f}s")

    if laps:
        lap_elapsed = sum(float(l.get("total_elapsed_time") or 0) for l in laps)
        lap_distance = sum(float(l.get("total_distance") or 0) for l in laps)
        if abs(lap_elapsed - elapsed) > 2:
            problems.append(f"分段时长之和 {lap_elapsed:.0f}s ≠ 总时长 {elapsed:.0f}s")
        if abs(lap_distance - distance) > max(2.0, distance * 0.005):
            problems.append(f"分段距离之和 {lap_distance:.1f}m ≠ 总距离 {distance:.1f}m")
        if session.get("num_laps") and int(session["num_laps"]) != len(laps):
            problems.append(f"num_laps={session['num_laps']} 与实际分段数 {len(laps)} 不一致")
        sport = session.get("sport")
        is_running = sport in (1, "running", "trail_running") or "running" in str(sport).lower()
        if not is_running:
            problems.append(f"非跑步类型不应写 lap（sport={sport}，{len(laps)} 段）")
    elif session.get("num_laps"):
        problems.append("session 声明了分段但文件里没有 lap 消息")

    activities = messages.get("activity_mesgs") or []
    if activities and end is not None:
        raw_local = activities[0].get("local_timestamp")
        # local_timestamp 是 uint32（FIT 纪元秒），SDK 不会转成 datetime
        if isinstance(raw_local, datetime):
            local_ts = epoch(raw_local)
        elif isinstance(raw_local, (int, float)):
            local_ts = int(raw_local) + FIT_EPOCH
        else:
            local_ts = None
        if local_ts is None:
            problems.append("activity 缺少 local_timestamp")
        else:
            diff = local_ts - end
            if diff % 900 != 0 or not -12 * 3600 <= diff <= 14 * 3600:
                problems.append(f"local_timestamp 与结束时间差 {diff}s，不是合法的时区偏移")

    stamps = [epoch(r.get("timestamp")) for r in records]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        problems.append("没有带时间戳的 record")
    else:
        if stamps != sorted(stamps):
            problems.append("record 时间戳不是递增的")
        if start is not None and stamps[0] < start:
            problems.append("首条 record 早于 session.start_time")
        if end is not None and stamps[-1] > end:
            problems.append("末条 record 晚于 session.timestamp")
        for rec in records:
            lat, lon = rec.get("position_lat"), rec.get("position_long")
            if lat is not None and not -85 <= float(lat) / (2 ** 31 / 180) <= 85:
                problems.append("存在越界纬度")
                break
            if lon is not None and not -180 <= float(lon) / (2 ** 31 / 180) <= 180:
                problems.append("存在越界经度")
                break

    if source:
        src_duration = float(source.get("duration_s") or 0)
        src_elapsed = float(source.get("elapsed_s") or src_duration)
        src_distance = float(source.get("distance_m") or 0)
        if src_elapsed and abs(elapsed - src_elapsed) > 2:
            problems.append(f"总时长与源数据差 {abs(elapsed - src_elapsed):.0f}s")
        if src_duration and abs(timer - src_duration) > 2:
            problems.append(f"有效时长与源数据差 {abs(timer - src_duration):.0f}s")
        if src_distance and abs(distance - src_distance) > max(2.0, src_distance * 0.01):
            problems.append(f"距离与源数据差 {abs(distance - src_distance):.1f}m")
        n_src = len(source.get("samples") or [])
        if n_src and abs(len(records) - n_src) > max(2, n_src * 0.02):
            warnings.append(f"采样点数 {len(records)} 与源 {n_src} 不一致")
        if source.get("avg_hr") and session.get("avg_heart_rate"):
            if abs(int(session["avg_heart_rate"]) - int(source["avg_hr"])) > 3:
                warnings.append("平均心率与源数据相差超过 3 bpm")

    return {
        "file": path.name,
        "bytes": size,
        "records": len(records),
        "laps": len(laps),
        "elapsed_s": round(elapsed, 1),
        "timer_s": round(timer, 1),
        "distance_m": round(distance, 1),
        "problems": problems,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="FIT 自检")
    ap.add_argument("--fit-dir", default="out")
    ap.add_argument("--workouts", default="", help="源 workouts.json，用于数值比对")
    ap.add_argument("--report", default="audit.json")
    args = ap.parse_args()

    fit_dir = Path(args.fit_dir).expanduser()
    files = sorted(fit_dir.glob("*.fit"))
    if not files:
        raise SystemExit(f"{fit_dir} 里没有 .fit 文件")

    sources: dict[str, dict] = {}
    if args.workouts:
        data = json.loads(Path(args.workouts).expanduser().read_text(encoding="utf-8"))
        items = data["workouts"] if isinstance(data, dict) else data
        from fit_encode import file_name  # 同目录脚本复用命名规则

        for item in items:
            sources[file_name(item)] = item

    rows, bad = [], 0
    for path in files:
        row = audit_file(path, sources.get(path.name))
        rows.append(row)
        if row["problems"]:
            bad += 1
            print(f"  × {row['file']}")
            for problem in row["problems"]:
                print(f"      - {problem}")
        else:
            note = f"（{len(row['warnings'])} 条提醒）" if row["warnings"] else ""
            print(f"  ✓ {row['file']}  {row['records']} 点 / {row['laps']} 段{note}")

    report = {"summary": {"files": len(rows), "with_problems": bad}, "details": rows}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n· {len(rows)} 个文件，{bad} 个有问题 → {args.report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
