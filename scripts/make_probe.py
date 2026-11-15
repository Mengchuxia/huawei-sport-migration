#!/usr/bin/env python3
"""生成单变量探针：只改运动类型，判断某个类型当前还能不能导入。

平台支持的类型会变（新版本可能放开或收紧）。与其相信文档里的旧结论，
不如用自己的一条真实记录生成几个只差类型的文件，各传一次看结果。

    python scripts/make_probe.py --input workouts.json --out-dir probes
    python scripts/make_probe.py --input workouts.json --out-dir probes --sports running,badminton,pingpong

两点约定（很重要）：
- 探针时间会被改到样本当天的凌晨 3 点，每个类型再错开 1 分钟，
  这样不会和你待导入的真实记录撞到同一分钟，也不会被当成"已存在"跳过。
- 探针导入后就是一条真实运动记录，本包删不掉。测完请在华为运动健康 App 里手动删除。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fit_encode import SPORT_MAP, encode, file_name


def shifted_start(text: str, minutes: int, date: str = "") -> str:
    """把样本的开始时间挪到一个不容易撞车的时刻，保留原来的时区偏移。"""
    moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    if date:
        moment = datetime.fromisoformat(date + "T03:00:00").replace(tzinfo=moment.tzinfo)
    moment = moment.replace(hour=3, minute=0, second=0, microsecond=0)
    return (moment + timedelta(minutes=minutes)).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description="生成运动类型探针")
    ap.add_argument("--input", default="workouts.json")
    ap.add_argument("--out-dir", default="probes")
    ap.add_argument("--index", type=int, default=0, help="用第几条记录做样本")
    ap.add_argument("--date", default="", help="探针日期（YYYY-MM-DD），默认用样本当天")
    ap.add_argument("--sports", default="running,walking,cycling,strength,badminton,"
                                        "pingpong,rowing_machine,climbing,e_sports,swimming")
    args = ap.parse_args()

    data = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    items = data["workouts"] if isinstance(data, dict) else data
    if not items:
        raise SystemExit("workouts.json 是空的")
    base = items[max(0, min(args.index, len(items) - 1))]

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [s.strip() for s in args.sports.split(",") if s.strip() in SPORT_MAP]
    if not wanted:
        raise SystemExit("没有可用的运动类型")

    for position, sport in enumerate(wanted):
        item = copy.deepcopy(base)
        item["sport"] = sport
        item["id"] = f"probe-{sport}"
        item["start_time"] = shifted_start(base["start_time"], position, args.date)
        data_bytes = encode(item, lap_mode="auto")
        target = out_dir / file_name(item)
        target.write_bytes(data_bytes)
        print(f"  ✓ {target.name}  {len(data_bytes) / 1024:.1f} KB")

    print(f"\n· 生成 {len(wanted)} 个探针 → {out_dir}")
    print("· 判断方法：每个文件单独传一次，再核验服务端是否出现对应时间的记录；"
          "不同时上传多个，避免无法归因。")
    print("· 注意：探针会作为真实运动记录入库，本包删不掉，测完请在 App 里手动删除。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
