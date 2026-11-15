#!/usr/bin/env python3
"""浏览器侧公共逻辑：登录态、结果弹窗、服务端活动记录。

华为导入页是网页应用，导入结果有两处来源：
1. 页面弹窗（可能是上一次的残留，不能单独作为依据）
2. 服务端活动记录接口（真实落库结果，核验以它为准）

登录态保存在用户目录下的独立浏览器配置里，脚本从不接触账号密码。
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

IMPORT_URL = "https://h5hosting.dbankcdn.com/cch5/healthkit/data-import/pages/oauth-callback.html"
PROFILE_DIR = Path.home() / ".huawei-sport-migration" / "browser-profile"
STATE_DIR = Path.home() / ".huawei-sport-migration"

FETCH_ACTIVITIES_JS = r"""(()=>{
const cfg=window.SYS_GLOBAL_CONFIG&&window.SYS_GLOBAL_CONFIG.nrcUrl;
if(!cfg) return Promise.resolve({err:'页面未加载完成或不是导入页'});
const base=cfg.viteApiBaseUrl_CN, cid=cfg.clientId, tk=sessionStorage.getItem('accessToken');
if(!tk) return Promise.resolve({err:'未取到登录令牌，请先在浏览器里登录'});
const H={Authorization:'Bearer '+tk,'x-client-id':cid,'Content-Type':'application/json'};
const pad=n=>(n<10?'0':'')+n;
const key=ms=>{const d=new Date(ms);return ''+d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate())+'_'+pad(d.getHours())+pad(d.getMinutes());};
const q=(s,e)=>base+'/healthkit/v2/activityRecords?startTime='+s+'&endTime='+e+'&limit=20&order=endTimeDesc&sportDataSource=0';
const start=Date.parse('__SINCE__T00:00:00');
let end=Date.now(), out=[], guard=0;
function finish(){
  const seen={},items=[];
  out.forEach(x=>{
    const id=x.id==null?('_'+items.length):String(x.id);
    if(!seen[id]){seen[id]=1;items.push(x);}
  });
  return {n:items.length,items:items};
}
function step(){
  if(end<=start) return Promise.resolve(finish());
  if(guard>=500) return Promise.resolve({err:'服务端记录超出分页上限（约 1 万条），请用 --since 缩小查询范围'});
  guard++;
  return fetch(q(start,end),{headers:H}).then(r=>r.json().then(j=>{
    const arr=(j&&j.activityRecord)||[];
    if(!arr.length) return true;
    arr.forEach(x=>out.push({id:x.id,st:x.startTime,et:x.endTime,type:x.activityType,key:key(x.startTime)}));
    const last=arr[arr.length-1];
    // 用 endTime 回退 1 秒翻页：用 startTime 会漏掉跨越这一页边界的记录
    const next=(last.endTime||last.startTime)-1000;
    if(!next||next>=end) return true;
    end=next;
    return false;
  })).then(done=>done?finish():step());
}
return step();
})()"""


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # noqa: BLE001
        raise SystemExit(
            "缺少 Playwright。安装：pip install playwright && playwright install chromium"
        ) from exc
    return sync_playwright


def launch(pw):
    """打开持久化浏览器；优先用系统 Edge，其次系统 Chrome，最后内置 Chromium。"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    for channel in ("msedge", "chrome", None):
        try:
            kwargs = {
                "user_data_dir": str(PROFILE_DIR),
                "headless": False,
                "args": ["--start-maximized"],
                "viewport": None,
            }
            if channel:
                kwargs["channel"] = channel
            context = pw.chromium.launch_persistent_context(**kwargs)
            page = context.pages[0] if context.pages else context.new_page()
            return context, page
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{channel or 'chromium'}: {type(exc).__name__}")
    raise SystemExit("无法启动浏览器（" + "；".join(errors) +
                     "）。可执行 playwright install chromium 后重试。")


def logged_in(page) -> bool:
    try:
        if "loginAuth" in page.url or "oauth-login" in page.url:
            return False
        return page.locator("input[type=file]").count() > 0
    except Exception:  # noqa: BLE001
        return False


def open_import_page(page, timeout_s: float = 180.0) -> None:
    page.goto(IMPORT_URL, wait_until="domcontentloaded")
    if logged_in(page):
        return
    print("· 需要登录：请在弹出的浏览器窗口完成华为账号登录（扫码或短信验证码）。")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        if logged_in(page):
            print("· 登录完成")
            return
    raise SystemExit("等待登录超时。重新运行本命令即可，登录态会保存在本地浏览器配置里。")


def close_dialog(page) -> None:
    """关闭导入结果弹窗；关不掉就会读到上一次的结果，因此必须确认已关闭。"""
    for selector in (".importResultBox .dialog-footerbtn", ".el-dialog__close"):
        try:
            locator = page.locator(selector)
            if locator.count():
                locator.first.click(timeout=2000)
                break
        except Exception:  # noqa: BLE001
            continue
    time.sleep(0.6)
    try:
        page.locator(".importResultBox .dialog-footerbtn").first.wait_for(state="hidden", timeout=3000)
    except Exception:  # noqa: BLE001
        pass


def dialog_text(page) -> str:
    try:
        boxes = page.locator(".importResultBox")
        for index in range(boxes.count() - 1, -1, -1):
            box = boxes.nth(index)
            if box.is_visible():
                text = box.inner_text().strip()
                if "共导入" in text:
                    return text.replace("\n", " ")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def clear_file_list(page) -> int:
    try:
        removed = page.evaluate(
            "(()=>{const items=document.querySelectorAll('.el-upload-list li').length;"
            "document.querySelectorAll('.el-upload-list').forEach(x=>x.innerHTML='');"
            "return items})()")
    except Exception:  # noqa: BLE001
        return 0
    time.sleep(0.4)
    return int(removed or 0)


def upload_batch(page, files: list[Path], wait_s: float = 90.0) -> dict:
    close_dialog(page)
    clear_file_list(page)
    page.set_input_files("input[type=file]", [str(p.resolve()) for p in files])
    time.sleep(0.8)
    listed = page.evaluate(
        "(()=>[...document.querySelectorAll('.el-upload-list li')]"
        ".map(x=>x.innerText.trim().replace(/\\n/g,' ')))()") or []
    if len(listed) != len(files):
        clear_file_list(page)
        page.set_input_files("input[type=file]", [str(p.resolve()) for p in files])
        time.sleep(1.2)
        listed = page.evaluate(
            "(()=>[...document.querySelectorAll('.el-upload-list li')]"
            ".map(x=>x.innerText.trim().replace(/\\n/g,' ')))()") or []

    clicked = page.evaluate(
        "(()=>{const b=document.querySelector('.button_import');"
        "if(!b)return 'no-button';b.click();return 'clicked'})()")
    text, waited = "", 0.0
    while waited < wait_s:
        time.sleep(1.5)
        waited += 1.5
        text = dialog_text(page)
        if text:
            break
    close_dialog(page)
    return {"files": [p.name for p in files], "listed": len(listed),
            "clicked": clicked, "dialog": text, "waited_s": waited}


def fetch_activities(page, since: str = "2020-01-01") -> list[dict]:
    js = FETCH_ACTIVITIES_JS.replace("__SINCE__", since)
    result = page.evaluate(js)
    if not isinstance(result, dict):
        raise SystemExit(f"读取服务端记录失败：{result}")
    if result.get("err"):
        raise SystemExit(f"读取服务端记录失败：{result['err']}")
    return result.get("items") or []


def minute_of(epoch: int) -> str:
    """本地时区的分钟标识，与服务端记录、文件名保持同一口径。"""
    return datetime.fromtimestamp(epoch).strftime("%Y%m%d_%H%M")


def span_of(item: dict) -> float | None:
    start, end = item.get("st"), item.get("et")
    if start is None or end is None:
        return None
    return max(0.0, (float(end) - float(start)) / 1000.0)


def match_key(start_epoch: int, elapsed) -> str:
    """比对键：开始时间（分钟）+ 时长（秒）。

    只到分钟会把「同一分钟的两场不同运动」当成同一条；只有秒级时间戳又对不上
    平台侧可能存在的 1 秒取整差。加上时长后，同分钟不同时长能分开，
    时长相差 5 秒以内则回退到分钟级兜底。
    """
    return f"{minute_of(int(start_epoch))}_{int(round(float(elapsed or 0)))}"


class RecordIndex:
    """服务端活动记录的比对索引，上传与核验共用同一套口径。"""

    def __init__(self, items: list[dict]):
        self.by_key: dict[str, list[dict]] = defaultdict(list)
        self.by_minute: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            start = item.get("st")
            if start is None:
                continue
            epoch = int(start) // 1000
            self.by_minute[minute_of(epoch)].append(item)
            span = span_of(item)
            if span is not None:
                self.by_key[match_key(epoch, span)].append(item)

    def find(self, start_epoch: int, elapsed) -> tuple[list[dict], bool]:
        """返回 (匹配到的记录, 是否无法确认)。

        - 精确键命中：可能 1 条（已入库）或多条（重复）
        - 精确键未命中但同分钟只有一条且时长接近：视为已入库
        - 同分钟多条、时长都对不上：无法确认，调用方不要据此判断缺失或重复
        """
        if elapsed:
            exact = self.by_key.get(match_key(start_epoch, elapsed))
            if exact:
                return exact, False
        candidates = self.by_minute.get(minute_of(start_epoch), [])
        if not candidates:
            return [], False
        if elapsed:
            near = [c for c in candidates
                    if span_of(c) is not None and abs(span_of(c) - float(elapsed)) <= 5]
            if near:
                return near, False
        if len(candidates) == 1:
            return candidates, False
        return [], True


def fit_identity(path: Path) -> tuple[int, float, str] | None:
    """从 FIT 文件读出 (开始时间戳, 总时长, 运动名)，用于没有源清单的文件比对。"""
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError:
        return None
    try:
        messages, errors = Decoder(Stream.from_file(str(path))).read()
        if errors:
            return None
        session = (messages.get("session_mesgs") or [{}])[0]
        start = session.get("start_time")
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if start is None:
            return None
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed = float(session.get("total_elapsed_time") or 0)
        return int(start.timestamp()), elapsed, str(session.get("sport") or "")
    except Exception:  # noqa: BLE001
        return None


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
