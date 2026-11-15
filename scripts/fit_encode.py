#!/usr/bin/env python3
"""把 workouts.json 编码成符合 Garmin FIT Activity 规范、可被华为运动健康导入的 FIT 文件。

依赖 garmin-fit-sdk（官方编码器）。用法：

    python scripts/fit_encode.py --input workouts.json --out-dir out
    python scripts/fit_encode.py --input workouts.json --out-dir out --lap-mode km --cadence spm

规范要点（决定能否导入，改动前先读 references/fit-encoding.md）：
- 必需消息：file_id / device_info / sport / event / record / lap / session / activity
- lap 时长与距离之和必须等于 session；record 时间戳必须落在 session 区间内
- total_elapsed_time = 墙钟跨度（含暂停），total_timer_time = 有效运动时长
- 非跑步类型不写 lap：华为报 "This activityType is not support section."
- 步频按 FIT 规范写 rpm（跑步 = 步/分 ÷ 2），且只有存在逐点步频时才写汇总
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SEMICIRCLES = 2 ** 31 / 180

# 设备标识：这组取值是实测可导入的组合，仅用于兼容，不代表真实设备。
MANUFACTURER = 1
PRODUCT = 3121
SERIAL = 3_912_456_781
PRODUCT_NAME = "Forerunner 955"

# (sport, sub_sport)；数值取自 Garmin FIT Profile，不要改。
SPORT_MAP: dict[str, tuple[int, int]] = {
    "running": (1, 2),
    "walking": (11, 30),
    "cycling": (2, 7),
    "swimming": (5, 17),
    "strength": (10, 20),
    "triathlon": (18, 0),
    "hiking": (17, 0),
    "badminton": (64, 95),
    "pingpong": (64, 97),
    "table_tennis": (64, 97),
    "tennis": (8, 0),
    "rowing": (15, 0),
    "rowing_machine": (15, 14),
    "climbing": (31, 68),
    "rock_climbing": (31, 0),
    "e_sports": (63, 0),
    "esports": (63, 0),
    "basketball": (6, 0),
    "soccer": (7, 0),
    "golf": (25, 0),
}
FOOT_SPORTS = {"running", "walking", "hiking"}


def parse_time(value) -> int:
    """接受 ISO8601 字符串或 epoch 秒，返回 epoch 秒。"""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    # 不带时区时按运行机器的本地时区解释（导出的运动时间通常是本地时间）
    return int(dt.timestamp())


def _fit_ts(epoch: int) -> int:
    from garmin_fit_sdk import convert_datetime_to_timestamp

    return convert_datetime_to_timestamp(datetime.fromtimestamp(epoch, tz=timezone.utc))


def load_workouts(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "workouts" in data:
        data = data["workouts"]
    if not isinstance(data, list):
        raise SystemExit("workouts.json 顶层必须是数组，或 {\"workouts\": [...]}")
    return data


def sample_series(w: dict) -> list[dict]:
    """把 samples 规整为按时间递增、字段固定的列表；t 为相对开始的秒数。"""
    raw = w.get("samples") or []
    out: list[dict] = []
    last_t = -1
    for item in raw:
        if not isinstance(item, dict):
            continue
        t = item.get("t")
        if t is None:
            continue
        t = int(round(float(t)))
        if t <= last_t:
            continue
        last_t = t
        point = {"t": t}
        for key in ("hr", "cad", "speed", "dist", "alt", "lat", "lon"):
            value = item.get(key)
            if value is None:
                continue
            if key in ("lat", "lon"):
                value = float(value)
                if not (-180 <= value <= 180):
                    continue
            else:
                value = float(value)
            point[key] = value
        if len(point) == 1:
            continue
        out.append(point)
    return out


def lap_cuts(samples: list[dict]) -> list[tuple[int, int]]:
    """每 1 km 一段；尾段不足 20 m 或不足 5 个点时并入上一段。"""
    if len(samples) < 4:
        return [(0, max(0, len(samples) - 1))]
    cuts: list[tuple[int, int]] = []
    start, target = 0, 1000.0
    for i, point in enumerate(samples):
        dist = point.get("dist")
        if dist is not None and dist >= target:
            cuts.append((start, i))
            start, target = i, target + 1000.0
    cuts.append((start, len(samples) - 1))
    if len(cuts) > 1:
        a, b = cuts[-1]
        seg = samples[a: b + 1]
        prev = samples[a - 1].get("dist") if a > 0 else 0
        tail = (seg[-1].get("dist") or 0) - (prev or 0) if seg else 0
        if tail < 20 or len(seg) < 5:
            cuts[-2] = (cuts[-2][0], b)
            cuts.pop()
    return [c for c in cuts if c[1] >= c[0]]


def encode(w: dict, *, lap_mode: str = "auto", cadence: str = "rpm") -> bytes:
    from garmin_fit_sdk import Encoder

    sport = str(w.get("sport", "")).strip().lower()
    if sport not in SPORT_MAP:
        raise ValueError(f"未识别的运动类型：{sport}")
    sp, ss = SPORT_MAP[sport]
    if w.get("sub_sport") is not None:
        ss = int(w["sub_sport"])

    start = parse_time(w["start_time"])
    duration = float(w.get("duration_s") or 0)
    elapsed = float(w.get("elapsed_s") or duration)
    distance = float(w.get("distance_m") or 0)
    calories = int(w.get("calories") or 0)
    samples = sample_series(w)

    if samples:
        start = min(start, start + samples[0]["t"])
        end = start + max(elapsed, samples[-1]["t"])
    else:
        end = start + max(1.0, elapsed)
    elapsed = float(max(1, end - start))
    timer = float(max(1, min(duration or elapsed, elapsed)))
    is_foot = sport in FOOT_SPORTS
    if lap_mode == "auto":
        lap_mode = "km" if sport == "running" else "none"
    write_laps = lap_mode != "none"

    enc = Encoder()
    enc.write_mesg({
        "mesg_num": 0, "type": 4, "manufacturer": MANUFACTURER, "product": PRODUCT,
        "serial_number": SERIAL, "time_created": _fit_ts(int(end)),
    })
    enc.write_mesg({"mesg_num": 49, "software_version": 100, "hardware_version": 1})
    enc.write_mesg({
        "mesg_num": 23, "timestamp": _fit_ts(start), "device_index": 0, "device_type": 0,
        "manufacturer": MANUFACTURER, "product": PRODUCT, "product_name": PRODUCT_NAME,
        "serial_number": SERIAL, "software_version": 263, "hardware_version": 1,
        "battery_status": 1,
    })
    enc.write_mesg({"mesg_num": 12, "sport": sp, "sub_sport": ss, "name": sport})
    enc.write_mesg({"mesg_num": 21, "timestamp": _fit_ts(start),
                    "event": 0, "event_type": 0, "event_group": 0})

    if not samples:
        rec = {"mesg_num": 20, "timestamp": _fit_ts(start), "distance": distance}
        if w.get("avg_hr"):
            rec["heart_rate"] = int(w["avg_hr"])
        enc.write_mesg(rec)

    cuts = lap_cuts(samples) if samples else [(0, -1)]
    if lap_mode == "single" and samples:
        cuts = [(0, len(samples) - 1)]

    bounds: list[float] = [float(start)]
    for i, (a, _b) in enumerate(cuts):
        if i == 0:
            continue
        seg = samples[a:]
        bounds.append(float(start + seg[0]["t"]) if seg else bounds[-1])
    bounds.append(float(end))
    if len(bounds) != len(cuts) + 1:
        bounds = [float(start), float(end)]
        cuts = [(0, len(samples) - 1)] if samples else [(0, -1)]
    lap_times = [bounds[i + 1] - bounds[i] for i in range(len(cuts))]

    raw_dists: list[float] = []
    prev_end = 0.0
    for a, b in cuts:
        seg = samples[a: b + 1] if a <= b else []
        end_dist = float(seg[-1].get("dist") or 0) if seg else distance
        raw_dists.append(max(0.0, end_dist - prev_end))
        prev_end = end_dist
    sum_d = sum(raw_dists) or 1.0
    lap_dists = [distance * d / sum_d for d in raw_dists]

    def cadence_value(spm: float):
        if cadence == "none" or not spm:
            return None
        value = spm if (cadence == "spm" or not is_foot) else spm / 2.0
        return int(min(254, max(0, round(value))))

    last_written = -1
    cal_used = 0
    span = max(1.0, (samples[-1]["t"] - samples[0]["t"])) if samples else 1.0

    for order, (a, b) in enumerate(cuts):
        seg = samples[a: b + 1] if a <= b else []
        for point in seg:
            t_abs = start + point["t"]
            if t_abs <= last_written or t_abs < start or t_abs > end:
                continue
            last_written = t_abs
            rec = {"mesg_num": 20, "timestamp": _fit_ts(int(t_abs))}
            if point.get("lat") is not None and point.get("lon") is not None:
                rec["position_lat"] = int(point["lat"] * SEMICIRCLES)
                rec["position_long"] = int(point["lon"] * SEMICIRCLES)
            if point.get("alt") is not None:
                rec["altitude"] = float(point["alt"])
                rec["enhanced_altitude"] = float(point["alt"])
            if point.get("dist") is not None:
                rec["distance"] = float(point["dist"])
            if point.get("speed") is not None:
                speed = min(65.5, max(0.0, float(point["speed"])))
                rec["speed"] = speed
                rec["enhanced_speed"] = speed
            if point.get("hr"):
                rec["heart_rate"] = int(point["hr"])
            if point.get("cad"):
                value = cadence_value(float(point["cad"]))
                if value is not None:
                    rec["cadence"] = value
            if len(rec) == 2:
                rec["distance"] = float(point.get("dist") or 0)
            enc.write_mesg(rec)

        lap_time = lap_times[order]
        lap_dist = lap_dists[order]
        hrs = [float(p["hr"]) for p in seg if p.get("hr")]
        speeds = [float(p["speed"]) for p in seg if p.get("speed") is not None]
        cads = [float(p["cad"]) for p in seg if p.get("cad")]

        if calories:
            if order == len(cuts) - 1:
                lap_cal = max(0, calories - cal_used)
            else:
                lap_cal = min(int(round(calories * lap_time / span)), max(0, calories - cal_used))
            cal_used += lap_cal
        else:
            lap_cal = 0

        lap = {
            "mesg_num": 19, "timestamp": _fit_ts(int(bounds[order + 1])),
            "start_time": _fit_ts(int(bounds[order])),
            "total_elapsed_time": float(lap_time),
            "total_timer_time": float(lap_time) * (timer / elapsed),
            "total_distance": lap_dist, "total_calories": lap_cal,
            "sport": sp, "sub_sport": ss, "event": 9, "event_type": 1,
        }
        if hrs:
            lap["avg_heart_rate"] = int(round(sum(hrs) / len(hrs)))
            lap["max_heart_rate"] = int(max(hrs))
            lap["min_heart_rate"] = int(min(hrs))
        if speeds:
            lap["avg_speed"] = float(sum(speeds) / len(speeds))
            lap["max_speed"] = float(max(speeds))
            lap["enhanced_avg_speed"] = float(sum(speeds) / len(speeds))
            lap["enhanced_max_speed"] = float(max(speeds))
        if cads:
            avg = cadence_value(sum(cads) / len(cads))
            peak = cadence_value(max(cads))
            if avg is not None:
                lap["avg_cadence"] = avg
            if peak is not None:
                lap["max_cadence"] = peak
        if write_laps:
            enc.write_mesg(lap)

    enc.write_mesg({"mesg_num": 21, "timestamp": _fit_ts(int(end)),
                    "event": 0, "event_type": 4, "event_group": 0})

    all_hr = [float(p["hr"]) for p in samples if p.get("hr")]
    all_speed = [float(p["speed"]) for p in samples if p.get("speed") is not None]
    all_cad = [float(p["cad"]) for p in samples if p.get("cad")]

    avg_hr = int(w["avg_hr"]) if w.get("avg_hr") else (int(round(sum(all_hr) / len(all_hr))) if all_hr else None)
    max_hr = int(w["max_hr"]) if w.get("max_hr") else (int(max(all_hr)) if all_hr else None)
    min_hr = int(w["min_hr"]) if w.get("min_hr") else (int(min(all_hr)) if all_hr else None)
    avg_speed = (distance / timer if distance > 0 and timer > 0 else None) or (
        sum(all_speed) / len(all_speed) if all_speed else None)
    max_speed = float(w["max_speed_mps"]) if w.get("max_speed_mps") else (
        max(all_speed) if all_speed else None)

    session = {
        "mesg_num": 18, "timestamp": _fit_ts(int(end)), "start_time": _fit_ts(start),
        "total_elapsed_time": elapsed, "total_timer_time": timer,
        "total_distance": distance,
        "sport": sp, "sub_sport": ss, "num_laps": len(cuts) if write_laps else 0,
        "event": 9, "event_type": 1, "trigger": 0,
    }
    if calories:
        session["total_calories"] = calories
    if write_laps:
        session["first_lap_index"] = 0
    if avg_hr:
        session["avg_heart_rate"] = avg_hr
    if max_hr:
        session["max_heart_rate"] = max_hr
    if min_hr:
        session["min_heart_rate"] = min_hr
    if avg_speed is not None:
        session["avg_speed"] = float(avg_speed)
        session["enhanced_avg_speed"] = float(avg_speed)
    if max_speed is not None:
        session["max_speed"] = float(max_speed)
        session["enhanced_max_speed"] = float(max_speed)
    if w.get("ascent_m"):
        session["total_ascent"] = int(w["ascent_m"])
    if w.get("descent_m"):
        session["total_descent"] = int(w["descent_m"])
    for key in ("avg_cadence_spm", "max_cadence_spm"):
        if w.get(key) and all_cad:
            target = "avg_cadence" if key.startswith("avg") else "max_cadence"
            value = cadence_value(float(w[key]))
            if value is not None:
                session[target] = value
    enc.write_mesg(session)

    if w.get("tz_offset_min") is not None:
        tz_min = int(w["tz_offset_min"])
    else:
        # 默认取运行机器的本地时区偏移，避免非中国时区用户时间错位
        offset = datetime.fromtimestamp(end).astimezone().utcoffset()
        tz_min = int(offset.total_seconds() // 60) if offset else 0
    activity = {
        "mesg_num": 34, "timestamp": _fit_ts(int(end)), "total_timer_time": timer,
        "num_sessions": 1, "type": 0, "event": 26, "event_type": 1,
        "local_timestamp": _fit_ts(int(end) + tz_min * 60),
    }
    enc.write_mesg(activity)
    return bytes(enc.close())


def file_name(w: dict) -> str:
    start = datetime.fromtimestamp(parse_time(w["start_time"]))
    sport = str(w.get("sport", "other")).lower()
    ident = str(w.get("id") or start.strftime("%Y%m%d_%H%M%S"))
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in ident)
    return f"{start:%Y%m%d_%H%M}_{sport}_{safe}.fit"


def main() -> int:
    ap = argparse.ArgumentParser(description="workouts.json → 华为何导入的 FIT")
    ap.add_argument("--input", default="workouts.json")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--lap-mode", choices=["auto", "km", "single", "none"], default="auto",
                    help="auto：跑步按公里分段，其余不写 lap（华为对非跑步拒收分段）")
    ap.add_argument("--cadence", choices=["rpm", "spm", "none"], default="rpm",
                    help="rpm=FIT 规范（跑步为步/分÷2）；spm=原值；none=不写")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.is_file():
        raise SystemExit(f"找不到输入文件：{src}")
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    workouts = load_workouts(src)
    ok, failed = 0, []
    for w in workouts:
        try:
            data = encode(w, lap_mode=args.lap_mode, cadence=args.cadence)
        except Exception as exc:  # noqa: BLE001
            failed.append((w.get("id") or w.get("start_time"), f"{type(exc).__name__}: {exc}"))
            continue
        target = out_dir / file_name(w)
        target.write_bytes(data)
        ok += 1
        print(f"  ✓ {target.name}  {len(data) / 1024:.1f} KB")
    print(f"\n· 生成 {ok} 个文件 → {out_dir}")
    if failed:
        print(f"· 失败 {len(failed)} 条：")
        for ident, reason in failed:
            print(f"    {ident}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
