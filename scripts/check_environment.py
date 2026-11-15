#!/usr/bin/env python3
"""启动前环境检查（只读，不安装、不联网、不读凭据）。

    python scripts/check_environment.py
    python scripts/check_environment.py --json

状态：
- ready        全部就绪
- partial      核心可用，缺少可选能力（无法自动上传/核验）
- needs_setup  缺少必需依赖
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)


def module_version(name: str) -> str:
    if importlib.util.find_spec(name) is None:
        return ""
    from importlib import metadata

    for candidate in (name, name.replace("_", "-")):
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    try:
        module = importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return "unknown"
    return str(getattr(module, "__version__", "") or "unknown")


def browser_hint() -> str:
    for name in ("msedge", "chrome", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/usr/bin/chromium"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def playwright_browser() -> str:
    """Playwright 自带的 Chromium 也能驱动导入，不能只看系统浏览器。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            path = pw.chromium.executable_path
        return path if path and Path(path).exists() else ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    python_ok = sys.version_info[:2] >= MIN_PYTHON
    fit_sdk = module_version("garmin_fit_sdk")
    playwright = module_version("playwright")
    browser = browser_hint()
    browser_note = "系统浏览器"
    if not browser:
        browser = playwright_browser()
        browser_note = "Playwright 内置 Chromium"

    checks = [
        {"id": "python", "ok": python_ok,
         "detail": f"{platform.python_version()}（需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+）"},
        {"id": "garmin-fit-sdk", "ok": bool(fit_sdk),
         "detail": fit_sdk or "未安装：pip install garmin-fit-sdk"},
        {"id": "playwright", "ok": bool(playwright),
         "detail": playwright or "未安装：pip install playwright && playwright install chromium"},
        {"id": "browser", "ok": bool(browser),
         "detail": f"{browser}（{browser_note}）" if browser
         else "未找到 Edge/Chrome，可用 playwright install chromium"},
    ]

    core_ok = checks[0]["ok"] and checks[1]["ok"]
    upload_ok = bool(playwright) and bool(browser)
    if not core_ok:
        status = "needs_setup"
    elif not upload_ok:
        status = "partial"
    else:
        status = "ready"

    if args.json:
        print(json.dumps({"status": status, "checks": checks}, ensure_ascii=False, indent=1))
        return 0 if status != "needs_setup" else 1

    print(f"总体状态：{status}")
    for item in checks:
        mark = "✓" if item["ok"] else "×"
        print(f"  {mark} {item['id']:<16} {item['detail']}")
    if status == "ready":
        print("\n可以直接运行：from_bridge/convert → fit_encode → fit_audit → huawei_upload → huawei_verify")
    elif status == "partial":
        print("\n转换、编码、自检可用；自动上传与核验需要 Playwright。")
        print("也可以跳过脚本，按 references/huawei-limits.md 在网页里手动分批导入。")
    else:
        print("\n先安装缺失的必需依赖，再重新运行本检查。")
    return 0 if status != "needs_setup" else 1


if __name__ == "__main__":
    sys.exit(main())
