#!/usr/bin/env python3
"""把 GPX / TCX / FIT 导出文件统一转成 workouts.json（后续编码的输入）。

    python scripts/convert.py --input ~/Downloads/export --output workouts.json
    python scripts/convert.py --input run.gpx --output workouts.json --sport running

支持 .gpx / .tcx / .fit 及其 .gz 压缩版本（Strava 批量导出为 activities/*.fit.gz）。
只读取用户本地文件，不联网。缺少的字段保持缺失，不做插值或造假。
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SPORT_FROM_FIT = {
    1: "running", 2: "cycling", 5: "swimming", 10: "strength", 11: "walking",
    15: "rowing", 17: "hiking", 18: "triathlon", 31: "climbing", 63: "e_sports",
    64: "racket", 6: "basketball", 7: "soccer", 25: "golf", 8: "tennis",
}
SUBSport_HINT = {2: "running", 30: "walking", 7: "cycling", 20: "strength",
                 17: "swimming", 95: "badminton", 97: "pingpong"}
NAME_HINT = {
    "running": "running", "run": "running", "跑步": "running",
    "walking": "walking", "walk": "walking", "步行": "walking",
    "cycling": "cycling", "bike": "cycling", "ride": "cycling", "骑行": "cycling",
    "swimming": "swimming", "swim": "swimming", "游泳": "swimming",
    "strength": "strength", "training": "strength", "力量": "strength",
    "badminton": "badminton", "羽毛球": "badminton",
}


def local(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone().replace(tzinfo=None).isoformat()


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def guess_sport(name: str, default: str = "") -> str:
    low = name.lower()
    for key, value in NAME_HINT.items():
        if key in low:
            return value
    return default


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1].lower()


def child_text(element: ET.Element, *names: str) -> str | None:
    for node in element.iter():
        if tag(node) in names and node.text and node.text.strip():
            return node.text.strip()
    return None


def parse_gpx(path: Path, sport: str) -> dict:
    root = ET.parse(path).getroot()
    points: list[dict] = []
    start = None
    for node in root.iter():
        if tag(node) != "trkpt":
            continue
        lat = node.get("lat")
        lon = node.get("lon")
        if lat is None or lon is None:
            continue
        time_text = child_text(node, "time")
        if not time_text:
            continue
        moment = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
        if start is None:
            start = moment
        point = {
            "t": int((moment - start).total_seconds()),
            "lat": float(lat), "lon": float(lon),
        }
        ele = child_text(node, "ele")
        if ele:
            point["alt"] = round(float(ele), 1)
        hr = child_text(node, "hr", "heartrate")
        if hr:
            point["hr"] = int(float(hr))
        cad = child_text(node, "cad", "cadence")
        if cad:
            point["cad"] = int(float(cad))
        points.append(point)
    if not points:
        raise ValueError("GPX 里没有带时间戳的轨迹点")
    return build_workout(path, sport or guess_sport(path.name, "running"), start, points)


def parse_tcx(path: Path, sport: str) -> dict:
    root = ET.parse(path).getroot()
    activity = None
    for node in root.iter():
        if tag(node) == "activity":
            activity = node
            break
    if activity is None:
        raise ValueError("TCX 里没有 Activity")
    sport_attr = (activity.get("Sport") or "").strip().lower()
    mapped = {"running": "running", "biking": "cycling", "cycling": "cycling"}.get(sport_attr)
    points: list[dict] = []
    start = None
    total_distance = 0.0
    total_calories = 0.0
    for node in activity.iter():
        if tag(node) == "trackpoint":
            time_text = child_text(node, "time")
            if not time_text:
                continue
            moment = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
            if start is None:
                start = moment
            point = {"t": int((moment - start).total_seconds())}
            lat = lon = None
            for sub in node.iter():
                name = tag(sub)
                if name == "latitude" and sub.text:
                    lat = float(sub.text)
                elif name == "longitude" and sub.text:
                    lon = float(sub.text)
                elif name == "altitudemeters" and sub.text:
                    point["alt"] = round(float(sub.text), 1)
                elif name == "distancemeters" and sub.text:
                    point["dist"] = round(float(sub.text), 2)
                elif name == "heartratebpm":
                    value = child_text(sub, "value")
                    if value:
                        point["hr"] = int(float(value))
                elif name in ("runcadence", "cadence") and sub.text:
                    point["cad"] = int(float(sub.text))
                elif name == "speed" and sub.text:
                    point["speed"] = round(float(sub.text), 3)
            if lat is not None and lon is not None:
                point["lat"], point["lon"] = lat, lon
            points.append(point)
        elif tag(node) == "lap":
            dist = child_text(node, "distancemeters")
            if dist:
                total_distance += float(dist)
            cal = child_text(node, "calories")
            if cal:
                total_calories += float(cal)
    if not points:
        raise ValueError("TCX 里没有 Trackpoint")
    workout = build_workout(path, sport or mapped or guess_sport(path.name, "running"), start, points)
    if total_distance:
        workout["distance_m"] = round(total_distance, 1)
    if total_calories:
        workout["calories"] = int(total_calories)
    return workout


def parse_fit(path: Path, sport: str) -> dict:
    from garmin_fit_sdk import Decoder, Stream  # 局部导入：没装依赖时其它格式仍可用

    messages, errors = Decoder(Stream.from_file(str(path))).read()
    if errors:
        raise ValueError(f"FIT 解码报错：{errors[0]}")
    sessions = messages.get("session_mesgs") or []
    if not sessions:
        raise ValueError("FIT 里没有 session")
    session = sessions[0]
    fit_sport = session.get("sport")
    sub = session.get("sub_sport")
    from fit_encode import SPORT_MAP  # 同目录脚本，复用同一套运动名

    if isinstance(fit_sport, str):
        name = fit_sport.lower() if fit_sport.lower() in SPORT_MAP else "other"
    elif isinstance(fit_sport, int):
        name = SPORT_FROM_FIT.get(fit_sport, "other")
    else:
        name = "other"
    if name in ("racket", "other"):
        if isinstance(sub, str) and sub.lower() in SPORT_MAP:
            name = sub.lower()
        elif isinstance(sub, int) and sub in SUBSport_HINT:
            name = SUBSport_HINT[sub]
    name = sport or name
    start_dt = session.get("start_time")
    if isinstance(start_dt, str):
        start_dt = datetime.fromisoformat(start_dt)
    if start_dt is None:
        raise ValueError("FIT session 缺少 start_time")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    start_epoch = int(start_dt.timestamp())
    points: list[dict] = []
    for rec in messages.get("record_mesgs") or []:
        moment = rec.get("timestamp")
        if moment is None:
            continue
        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        point = {"t": int(moment.timestamp()) - start_epoch}
        lat = rec.get("position_lat")
        lon = rec.get("position_long")
        if lat is not None and lon is not None:
            point["lat"] = round(float(lat) / (2 ** 31 / 180), 7)
            point["lon"] = round(float(lon) / (2 ** 31 / 180), 7)
        alt = rec.get("enhanced_altitude", rec.get("altitude"))
        if alt is not None:
            point["alt"] = round(float(alt), 1)
        dist = rec.get("distance")
        if dist is not None:
            point["dist"] = round(float(dist), 2)
        speed = rec.get("enhanced_speed", rec.get("speed"))
        if speed is not None:
            point["speed"] = round(float(speed), 3)
        hr = rec.get("heart_rate")
        if hr:
            point["hr"] = int(hr)
        cad = rec.get("cadence")
        if cad:
            point["cad"] = int(cad) * 2 if name in ("running", "walking", "hiking") else int(cad)
        if len(point) > 1:
            points.append(point)

    workout = build_workout(path, name, start_dt.replace(tzinfo=None), points)
    if not points:
        workout["samples"] = []
    workout["duration_s"] = int(round(float(session.get("total_timer_time") or workout["duration_s"])))
    workout["elapsed_s"] = int(round(float(session.get("total_elapsed_time") or workout["elapsed_s"])))
    if session.get("total_distance"):
        workout["distance_m"] = round(float(session["total_distance"]), 1)
    if session.get("total_calories"):
        workout["calories"] = int(session["total_calories"])
    for key, target in (("avg_heart_rate", "avg_hr"), ("max_heart_rate", "max_hr")):
        if session.get(key):
            workout[target] = int(session[key])
    return workout


def build_workout(path: Path, sport: str, start: datetime, points: list[dict]) -> dict:
    points.sort(key=lambda p: p["t"])
    if points and all(p.get("dist") is None for p in points):
        # 整个文件都没有距离：能算就用轨迹算，算不出就保持 0
        cumulative, last = 0.0, None
        for point in points:
            if point.get("lat") is not None and point.get("lon") is not None:
                if last is not None:
                    cumulative += haversine(last, (point["lat"], point["lon"]))
                last = (point["lat"], point["lon"])
            point["dist"] = round(cumulative, 2)
    elif points:
        # 部分点有距离：缺的沿用前值，不要用轨迹重算覆盖源数据
        last = 0.0
        for point in points:
            if point.get("dist") is None:
                point["dist"] = round(last, 2)
            else:
                last = point["dist"]
    distance = points[-1].get("dist") if points else None
    hrs = [p["hr"] for p in points if p.get("hr")]
    workout = {
        "id": path.stem,
        "sport": sport,
        "start_time": local(start),
        "duration_s": int(points[-1]["t"]) if points else 0,
        "elapsed_s": int(points[-1]["t"]) if points else 0,
        "distance_m": round(float(distance or 0), 1),
        "samples": points,
    }
    if hrs:
        workout["avg_hr"] = int(round(sum(hrs) / len(hrs)))
        workout["max_hr"] = int(max(hrs))
        workout["min_hr"] = int(min(hrs))
    return workout


PLAIN_SUFFIXES = {".gpx", ".tcx", ".fit"}


def is_supported(path: Path) -> bool:
    """Accept .gpx/.tcx/.fit, plus the .gz variants (Strava bulk export ships .fit.gz)."""
    suffix = path.suffix.lower()
    if suffix in PLAIN_SUFFIXES:
        return True
    if suffix == ".gz":
        return path.with_suffix("").suffix.lower() in PLAIN_SUFFIXES
    return False


def gunzip_to(path: Path, workdir: Path) -> Path:
    target = workdir / path.with_suffix("").name
    with gzip.open(path, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


def convert_one(path: Path, sport: str, workdir: Path | None = None) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        if workdir is None:
            raise ValueError("压缩文件需要临时目录")
        workout = convert_one(gunzip_to(path, workdir), sport, workdir)
        # 文件名用去掉 .gz 后的主干，避免出现 xxx.fit 这样的 id
        workout["id"] = path.with_suffix("").stem or workout["id"]
        return workout
    if suffix == ".gpx":
        return parse_gpx(path, sport)
    if suffix == ".tcx":
        return parse_tcx(path, sport)
    if suffix == ".fit":
        return parse_fit(path, sport)
    raise ValueError(f"不支持的格式：{path.suffix}")


def main() -> int:
    ap = argparse.ArgumentParser(description="GPX/TCX/FIT → workouts.json")
    ap.add_argument("--input", required=True, help="文件或目录")
    ap.add_argument("--output", default="workouts.json")
    ap.add_argument("--sport", default="", help="强制指定运动类型，留空则自动判断")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        raise SystemExit(f"找不到输入：{src}")
    if src.is_file():
        files, skipped = [src], []
    else:
        candidates = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith("."))
        files = [p for p in candidates if is_supported(p)]
        skipped = [p for p in candidates if not is_supported(p)]
    if not files:
        raise SystemExit("目录里没有 .gpx/.tcx/.fit（或对应的 .gz）文件")

    workouts, failed = [], []
    with tempfile.TemporaryDirectory(prefix="hwsm-convert-") as tmp:
        workdir = Path(tmp)
        for path in files:
            try:
                workouts.append(convert_one(path, args.sport, workdir))
                print(f"  ✓ {path.name} → {workouts[-1]['sport']}  "
                      f"{workouts[-1]['distance_m'] / 1000:.2f} km  "
                      f"{len(workouts[-1]['samples'])} 点")
            except Exception as exc:  # noqa: BLE001
                failed.append((path.name, f"{type(exc).__name__}: {exc}"))
                print(f"  × {path.name}: {exc}")
    if not workouts:
        raise SystemExit("没有成功转换的文件")
    Path(args.output).write_text(
        json.dumps({"workouts": workouts}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n· 写出 {len(workouts)} 条 → {args.output}")
    if skipped:
        names = "、".join(p.name for p in skipped[:6])
        more = f" 等 {len(skipped)} 个" if len(skipped) > 6 else ""
        print(f"· 跳过 {len(skipped)} 个不支持的文件：{names}{more}")
        xiaomi = [p for p in skipped
                  if p.suffix.lower() == ".csv" or "mi_fitness" in p.name.lower()]
        if xiaomi:
            print("  小米官方导出（CSV）与桥导出（JSON）需要先转成 workouts.json："
                  "桥导出用 from_bridge.py，CSV 见 references/source-data.md")
    if failed:
        print(f"· 失败 {len(failed)} 个（未写入输出）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
