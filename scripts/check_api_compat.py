#!/usr/bin/env python3
"""接口兼容性探测的主动询问入口（不执行任何写入账号的操作）。

华为导入页及其内部接口可能变化。运行本脚本会先询问使用者是否进行探测，
说明每种方式的步骤与影响，并输出所选方式应执行的检查清单。

本脚本不读取健康数据、不登录、不上传、不写入账号；选择结果仅记录到本地
.api_compat_choice.json，该文件应被 .gitignore 排除。

用法：
    python scripts/check_api_compat.py
    python scripts/check_api_compat.py --non-interactive --choice 1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

OPTIONS = {
    "1": {
        "name": "只读检查",
        "writes_account": False,
        "steps": [
            "打开导入页，记录当前文案：支持格式、支持类型、单批文件数、单文件体积、最早可导入日期",
            "在已登录页面上下文读取 activityRecords 一条记录，记录 activitySummary 顶层键与各结构字段名",
            "与 references/huawei-limits.md、references/field-reference.md 比对，输出差异清单",
            "不导入任何文件；如需进一步验证，再另行确认合成哨兵探测",
        ],
    },
    "2": {
        "name": "合成哨兵探测",
        "writes_account": True,
        "steps": [
            "生成两份同一开始时间、同一运动类型、内容不同的合成 FIT（不含真实个人信息）",
            "逐份导入，每次导入后回读服务端记录",
            "比对距离、时长、分段数、记录条数与统计字段集合，判断覆盖/跳过/追加",
            "记录服务端字段结构并注明核验日期",
            "在 App 内自行删除哨兵产生的记录；仓库不提供删除能力",
        ],
    },
    "3": {
        "name": "跳过",
        "writes_account": False,
        "steps": [
            "直接使用仓库现有结论，接受其可能过期",
            "导入后仍须以服务端记录核验，不以页面弹窗为准",
        ],
    },
}


def show_plan(choice: str) -> None:
    opt = OPTIONS[choice]
    print(f"\n已选择：{choice} {opt['name']}")
    if opt["writes_account"]:
        print("注意：该方式会向账号写入一条真实运动记录，且仓库不提供删除能力。")
        print("执行前请再次确认，并在完成后于 App 内自行删除。")
    print("应执行的检查：")
    for i, step in enumerate(opt["steps"], 1):
        print(f"  {i}. {step}")
    print("\n详细判据与最近一次核验记录见 references/api-compat-probe.md。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--non-interactive", action="store_true",
                    help="不提问，直接使用 --choice（用于已有明确授权的自动化流程）")
    ap.add_argument("--choice", choices=list(OPTIONS), default="3")
    args = ap.parse_args()

    print("华为导入页及服务端接口可能变化。是否进行接口兼容性探测？")
    print("  1 只读检查      不写入账号：页面文案 + 服务端字段结构比对")
    print("  2 合成哨兵探测  写入账号：合成 FIT 导入 + 回读，判断覆盖与字段结构")
    print("  3 跳过          使用仓库现有结论（可能过期）")
    if args.non_interactive:
        choice = args.choice
    else:
        try:
            choice = input("请选择 [1/2/3，默认 3]：").strip() or "3"
        except EOFError:
            choice = "3"
        if choice not in OPTIONS:
            print("输入无效，按「跳过」处理。")
            choice = "3"

    show_plan(choice)
    record = {
        "choice": choice, "option": OPTIONS[choice]["name"],
        "writes_account": OPTIONS[choice]["writes_account"],
        "at": datetime.now().isoformat(timespec="seconds"),
        "note": "本文件仅记录选择，不代表已执行探测，也不构成任何保证。",
    }
    out = Path(".api_compat_choice.json")
    try:
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"选择已记录到 {out}（本地文件，不应提交到版本库）。")
    except OSError as exc:
        print(f"无法写入选择记录：{exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
