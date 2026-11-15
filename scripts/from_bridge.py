#!/usr/bin/env python3
"""把 mi_fitness_data_bridge 的 JSON 导出转成 workouts.json。

    python scripts/from_bridge.py --input exports/mi_fitness.json --output workouts.json
    python scripts/from_bridge.py --input mi_fitness.json --no-derive

桥导出的结构是 {"records": {"workouts": [...], "workout_detail": [...], "workout_gps": [...]}}，
三张表按 workout_id 关联：

- workouts      每场一行（汇总），时长、卡路里、心率、步频
- workout_detail 逐秒样本，心率齐全；步频、累计距离只有部分场次有
- workout_gps    轨迹点，含纬度/经度/速度；没有海拔

源数据没有的字段就留空：不补海拔、不造心率、不插步频。距离和速度优先用源数据，
源数据缺失时按“有 GPS 用 GPS 里程，没有 GPS 按总里程与时间轴线性还原”的顺序处理，
可以用 --no-derive 关掉最后这类派生，只保留源数据里真实存在的值。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# 桥导出的 activity_type → 本包规范类型（fit_encode.SPORT_MAP 的键）
SPORT_MAP = {
    "running": "running",
    "walking": "walking",
    "outdoor_riding": "cycling",
    "indoor_riding": "cycling",
    "cycling": "cycling",
    "swimming": "swimming",
    "free_training": "strength",
    "strength_training": "strength",
    "cross_fit": "strength",
    "badminton": "badminton",
    "pingpong": "pingpong",
    "table_tennis": "pingpong",
    "tennis": "tennis",
    "basketball": "basketball",
    "soccer": "soccer",
    "football": "soccer",
    "golf": "golf",
    "rowing_machine": "rowing_machine",
    "rowing": "rowing",
    "climbing": "climbing",
    "hiking": "hiking",
    "mountaineering": "hiking",
    "e_sports": "e_sports",
    "esports": "e_sports",
    "triathlon": "triathlon",
}
# 兜底：类型名里带这些词时按对应类型处理
SPORT_HINTS = (
    ("run", "running"), ("jog", "running"), ("walk", "walking"), ("hik", "walking"),
    ("cycl", "cycling"), ("rid", "cycling"), ("bike", "cycling"), ("swim", "swimming"),
    ("badminton", "badminton"), ("pingpong", "pingpong"), ("table_tennis", "pingpong"),
    ("row", "rowing_machine"), ("climb", "climbing"), ("tennis", "tennis"),
    ("basketball", "basketball"), ("soccer", "soccer"), ("golf", "golf"),
    ("strength", "strength"), ("training", "strength"), ("fit", "strength"),
)


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def resolve_sport(raw) -> str:
    text = str(raw or "").strip().lower()
    if text in SPORT_MAP:
        return SPORT_MAP[text]
    for hint, sport in SPORT_HINTS:
        if hint in text:
            return sport
    return "other"


def offset_minutes(start: datetime) -> int | None:
    if start.tzinfo is None:
        return None
    value = start.utcoffset()
    return int(value.total_seconds() // 60) if value else 0


def parse_moment(text) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def number(value) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def merge_samples(details: list[dict], gps: list[dict], limit_s: int) -> list[dict]:
    """按 offset_seconds 合并逐秒样本与轨迹点；超出时长范围的点丢弃。"""
    points: dict[int, dict] = {}

    def slot(offset) -> dict | None:
        try:
            t = int(round(float(offset)))
        except (TypeError, ValueError):
            return None
        if t < 0 or t > limit_s:
            return None
        return points.setdefault(t, {"t": t})

    for row in details:
        point = slot(row.get("offset_seconds"))
        if point is None:
            continue
        hr = number(row.get("heart_rate_bpm"))
        if hr and 20 <= hr <= 250:
            point["hr"] = int(hr)
        cad = number(row.get("cadence"))
        if cad and 0 < cad <= 300:
            point["cad"] = int(cad)
        dist = number(row.get("distance_m"))
        if dist is not None and dist >= 0:
            point["dist"] = round(dist, 2)

    for row in gps:
        point = slot(row.get("offset_seconds"))
        if point is None:
            continue
        lat, lon = number(row.get("latitude")), number(row.get("longitude"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            point["lat"] = round(lat, 7)
            point["lon"] = round(lon, 7)
        speed = number(row.get("speed_mps"))
        if speed is not None and 0 <= speed <= 65.5:
            point["speed"] = round(speed, 3)

    return [points[key] for key in sorted(points)]


def gps_distance(points: list[dict]) -> float:
    total, last = 0.0, None
    for point in points:
        if point.get("lat") is None or point.get("lon") is None:
            continue
        current = (point["lat"], point["lon"])
        if last is not None:
            total += haversine(last, current)
        last = current
    return total


def rebuild_from_gps(points: list[dict]) -> float:
    total, last = 0.0, None
    for point in points:
        if point.get("lat") is None or point.get("lon") is None:
            point["dist"] = round(total, 2)
            continue
        current = (point["lat"], point["lon"])
        if last is not None:
            total += haversine(last, current)
        last = current
        point["dist"] = round(total, 2)
    return total


def linear_distance(points: list[dict], total: float) -> None:
    start, end = points[0]["t"], points[-1]["t"]
    span = max(1, end - start)
    for point in points:
        point["dist"] = round(total * (point["t"] - start) / span, 2)


def resolve_distance(points: list[dict], total: float, derive: bool) -> str:
    """把逐点距离统一成累计值，返回处理方式。"""
    if len(points) < 2:
        return "none"
    known = [p["dist"] for p in points if p.get("dist") is not None]

    if not known:
        if gps_distance(points) > 0:
            measured = rebuild_from_gps(points)
            return "gps" if measured > 0 else "none"
        if derive and total > 0:
            linear_distance(points, total)
            return "derived"
        return "none"

    last = known[-1]
    monotonic = all(b >= a - 0.5 for a, b in zip(known, known[1:]))
    mode = "cumulative"
    if total > 0:
        if last > 0 and 0.8 <= last / total <= 1.25:
            mode = "cumulative"
        elif sum(known) > 0 and last < 0.5 * total and 0.8 <= sum(known) / total <= 1.25:
            mode = "delta"
        elif not monotonic:
            mode = "delta"
        elif last > total * 1.25:
            # 单位不一致（实测有设备按分米上报），按总里程等比压回
            factor = total / last
            for point in points:
                if point.get("dist") is not None:
                    point["dist"] = round(point["dist"] * factor, 2)
            mode = "scaled"
        elif last < total * 0.8:
            # 明细只覆盖一部分（中途丢点），不能当全程
            if gps_distance(points) > 0:
                rebuild_from_gps(points)
                return "gps"
            if derive:
                linear_distance(points, total)
                return "derived"
            return "partial"

    running = 0.0
    for point in points:
        value = point.get("dist")
        if value is None:
            point["dist"] = round(running, 2)
            continue
        if mode == "delta":
            running += value
        elif value >= running:
            running = value
        point["dist"] = round(running, 2)

    if total > 0 and running > 0:
        factor = total / running
        if 0.8 <= factor <= 1.25 and abs(factor - 1) > 0.01:
            for point in points:
                point["dist"] = round((point.get("dist") or 0) * factor, 2)
    return mode


def derive_speed(points: list[dict]) -> int:
    """源数据没有逐点速度时，按相邻两点的距离差回算；只对回算出来的点做 3 点均值压锯齿。"""
    if sum(1 for p in points if p.get("speed") is not None) >= max(5, len(points) * 0.5):
        return 0
    derived: list[int] = []
    previous = None
    for index, point in enumerate(points):
        if point.get("speed") is None and previous is not None:
            dt = point["t"] - previous["t"]
            if dt > 0 and point.get("dist") is not None and previous.get("dist") is not None:
                point["speed"] = round(max(0.0, (point["dist"] - previous["dist"]) / dt), 3)
                derived.append(index)
        previous = point
    if derived and len(derived) >= max(5, len(points) * 0.5):
        for index in derived:
            window = [points[i].get("speed") for i in (index - 1, index, index + 1)
                      if 0 <= i < len(points) and points[i].get("speed") is not None]
            if window:
                points[index]["speed"] = round(sum(window) / len(window), 3)
    return len(derived)


def elapsed_seconds(row: dict, start: datetime, end: datetime) -> int:
    span = int(round((end - start).total_seconds()))
    if span > 0:
        return span
    minutes = number(row.get("duration_minutes"))
    if minutes:
        return int(round(minutes * 60))
    duration = number(row.get("valid_duration_seconds"))
    return int(duration or 0)


def build_workout(row: dict, details: list[dict], gps: list[dict],
                  derive: bool) -> tuple[dict | None, dict]:
    sport = resolve_sport(row.get("activity_type") or row.get("sport_type"))
    start = parse_moment(row.get("start_at"))
    if start is None:
        return None, {"reason": "缺少 start_at", "sport": sport}
    end = parse_moment(row.get("end_at")) or start
    elapsed = elapsed_seconds(row, start, end)
    if elapsed <= 0:
        return None, {"reason": "时长为 0", "sport": sport}
    if end <= start:
        end = datetime.fromtimestamp(start.timestamp() + elapsed, tz=start.tzinfo)

    points = merge_samples(details, gps, elapsed)
    total = number(row.get("distance_m")) or 0.0
    if total <= 0 and points:
        measured = gps_distance(points)
        total = measured if measured > 1 else 0.0
    distance_mode = resolve_distance(points, total, derive)
    if distance_mode == "none" and points and points[-1].get("dist"):
        total = float(points[-1]["dist"])
    derived_speed = derive_speed(points) if derive else 0

    minutes = number(row.get("duration_minutes"))
    duration = number(row.get("valid_duration_seconds")) or (minutes * 60 if minutes else 0)
    if not duration or duration > elapsed:
        duration = elapsed

    workout: dict = {
        "id": str(row.get("workout_id") or row.get("id") or ""),
        "sport": sport,
        "start_time": start.isoformat(),
        "duration_s": int(round(duration)),
        "elapsed_s": int(elapsed),
        "distance_m": round(float(total or 0), 1),
        "samples": points,
    }
    calories = number(row.get("calories_kcal"))
    if calories:
        workout["calories"] = int(round(calories))
    for source, target in (("avg_heart_rate_bpm", "avg_hr"), ("max_heart_rate_bpm", "max_hr"),
                           ("min_heart_rate_bpm", "min_hr")):
        value = number(row.get(source))
        if value:
            workout[target] = int(round(value))
    for source, target in (("avg_cadence", "avg_cadence_spm"), ("max_cadence", "max_cadence_spm")):
        value = number(row.get(source))
        if value:
            workout[target] = int(round(value))
    for source, target in (("rise_height_m", "ascent_m"), ("fall_height_m", "descent_m")):
        value = number(row.get(source))
        if value:
            workout[target] = int(round(value))
    offset = offset_minutes(start)
    if offset is not None:
        workout["tz_offset_min"] = offset
    return workout, {"distance": distance_mode, "speed_derived": derived_speed, "sport": sport}


def load_records(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("records"), dict):
        return data["records"]
    if isinstance(data, dict) and "workouts" in data:
        return data
    raise SystemExit("输入不像桥导出：顶层既没有 records，也没有 workouts")


def main() -> int:
    ap = argparse.ArgumentParser(description="mi_fitness_data_bridge JSON → workouts.json")
    ap.add_argument("--input", required=True, help="桥导出的 mi_fitness.json")
    ap.add_argument("--output", default="workouts.json")
    ap.add_argument("--no-derive", action="store_true",
                    help="不派生源数据里没有的距离/速度（只保留 GPS 实测）")
    ap.add_argument("--sport", default="", help="强制指定运动类型，覆盖自动判断")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.is_file():
        raise SystemExit(f"找不到输入文件：{src}")
    records = load_records(src)

    details: dict[str, list[dict]] = defaultdict(list)
    for row in records.get("workout_detail") or []:
        details[str(row.get("workout_id"))].append(row)
    gps: dict[str, list[dict]] = defaultdict(list)
    for row in records.get("workout_gps") or []:
        gps[str(row.get("workout_id"))].append(row)

    rows = records.get("workouts") or []
    if not rows:
        raise SystemExit("records.workouts 是空的")

    workouts, skipped = [], []
    stats = Counter()
    for row in rows:
        key = str(row.get("workout_id") or row.get("id") or "")
        built, info = build_workout(row, details.get(key) or [], gps.get(key) or [], not args.no_derive)
        if built is None:
            skipped.append((key, info.get("reason")))
            continue
        if args.sport:
            built["sport"] = args.sport
        if built["sport"] == "other":
            skipped.append((key, "运动类型无法识别，用 --sport 指定"))
            continue
        workouts.append(built)
        stats[built["sport"]] += 1
        stats[f"距离:{info['distance']}"] += 1
        if info["speed_derived"]:
            stats["派生速度"] += 1
        if built["samples"]:
            stats["有逐点"] += 1

    workouts.sort(key=lambda item: item["start_time"])
    out = Path(args.output).expanduser()
    out.write_text(json.dumps({"workouts": workouts}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"· 读取 {len(rows)} 场，输出 {len(workouts)} 条，跳过 {len(skipped)} 条")
    kinds = {k: v for k, v in stats.items() if not k.startswith("距离:")}
    print("· 类型：" + "、".join(f"{k} {v}" for k, v in kinds.items()))
    modes = {k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("距离:")}
    print("· 逐点距离来源：" + "、".join(f"{k} {v}" for k, v in modes.items()))
    if stats["派生速度"]:
        print(f"· 其中 {stats['派生速度']} 场没有源速度，按距离差回算（--no-derive 可关闭）")
    for key, reason in skipped[:10]:
        print(f"  × {key}: {reason}")
    if len(skipped) > 10:
        print(f"  … 另有 {len(skipped) - 10} 条同类问题")
    print(f"· 写出 → {out}")
    return 0 if workouts else 1


if __name__ == "__main__":
    sys.exit(main())
