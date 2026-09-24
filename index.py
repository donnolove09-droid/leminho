import asyncio
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

app = FastAPI(title="Garena Bot")

# ============ State ============
LOG_BUFFER = deque(maxlen=3000)
LAST_SCREENSHOTS: deque = deque(maxlen=30)
RUN_HISTORY = deque(maxlen=200)
BATCH_TASK: Optional[asyncio.Task] = None
BATCH_STOP = asyncio.Event()
BATCH_STATE = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "started": None,
    "finished": None,
    "elapsed": None,
}

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
HARD_TIMEOUT = int(os.getenv("HARD_TIMEOUT", "60"))
HTML_FILE = Path(__file__).parent / "index.html"


def log(msg: str, tag: str = ""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = f"[{ts}]" + (f"[{tag}]" if tag else "")
    line = f"{prefix} {msg}"
    print(line, flush=True)
    LOG_BUFFER.append(line)


# ============ Screenshot helper ============
async def _save_shot(page, idx: int, username: str, tag: str):
    try:
        shot = await page.screenshot(full_page=False, timeout=5000)
        LAST_SCREENSHOTS.append({
            "idx": idx,
            "username": username,
            "tag": tag,
            "time": datetime.now().strftime("%H:%M:%S"),
            "data": shot,
        })
        log(f"📸 chụp [{tag}]", f"#{idx}")
    except Exception as e:
        log(f"! không chụp được: {e}", f"#{idx}")


async def _dump_buttons(page, idx: int):
    try:
        btns = await page.query_selector_all(
            "button, [role='button'], input[type='submit'], a"
        )
        log(f"tìm thấy {len(btns)} nút:", f"#{idx}")
        for i, b in enumerate(btns[:20]):
            try:
                txt = (await b.inner_text()).strip().replace("\n", " ")[:50]
                tag_name = await b.evaluate("el => el.tagName")
                dis = await b.get_attribute("disabled")
                vis = await b.is_visible()
                log(f"   [{i}] <{tag_name}> '{txt}' vis={vis} dis={dis}", f"#{idx}")
            except Exception:
                pass
    except Exception as e:
        log(f"! dump buttons lỗi: {e}", f"#{idx}")


async def _route_filter(route):
    try:
        rtype = route.request.resource_type
        if rtype in ("image", "media", "font", "stylesheet"):
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        try:
            await route.continue_()
        except Exception:
            pass


# ============ Core: 1 lần chạy ============
async def one_run(username: str, idx: int) -> dict:
    tag = f"#{idx}"
    t0 = time.time()
    result = {
        "idx": idx, "username": username, "ok": False,
        "step": None, "detail": None, "duration": 0,
    }

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage", "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions", "--disable-background-networking",
                    "--disable-sync", "--metrics-recording-only",
                    "--no-first-run", "--disable-default-apps",
                ],
            )
            context = await browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"),
                viewport={"width": 1366, "height": 768},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = await context.new_page()
            await page.route("**/*", _route_filter)

            log("→ goto Garena", tag)
            await page.goto(
                "https://account.garena.com/recovery?locale=vi-VN#/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            result["step"] = "loaded"

            try:
                username_input = await page.wait_for_selector(
                    'input[type="text"], input[name="username"], '
                    'input[placeholder*="Tài khoản"], input[placeholder*="tài khoản"]',
                    timeout=10000, state="visible",
                )
            except PlaywrightTimeout:
                log("✗ không thấy ô username", tag)
                await _dump_buttons(page, idx)
                await _save_shot(page, idx, username, "no_input")
                result["detail"] = "username_input_not_found"
                return result

            await username_input.fill(username)
            await username_input.press("Tab")
            log(f"✓ nhập '{username}'", tag)
            result["step"] = "username_filled"

            next_btn = None
            for _ in range(20):
                for sel in (
                    'button:has-text("Tiếp theo")',
                    'button:has-text("Next")',
                    'button:has-text("Tiếp tục")',
                    'button[type="submit"]',
                ):
                    try:
                        b = await page.query_selector(sel)
                        if b and await b.is_visible():
                            if await b.get_attribute("disabled") is None:
                                next_btn = b
                                break
                    except Exception:
                        pass
                if next_btn:
                    break
                await asyncio.sleep(0.2)

            if not next_btn:
                log("✗ nút Tiếp theo không enable", tag)
                await _dump_buttons(page, idx)
                await _save_shot(page, idx, username, "next_disabled")
                result["detail"] = "next_button_not_found_or_disabled"
                return result

            await next_btn.click()
            log("✓ click Tiếp theo", tag)
            result["step"] = "next_clicked"

            try:
                await page.wait_for_selector(
                    'input[maxlength="1"], input[type="tel"], '
                    'input[autocomplete="one-time-code"], input[type="number"]',
                    timeout=8000, state="visible",
                )
                result["step"] = "otp_form_shown"
                log("✓ form OTP hiện", tag)
            except PlaywrightTimeout:
                result["detail"] = "otp_form_not_found"
                log("! không thấy form OTP", tag)

            await _save_shot(page, idx, username, "final")
            result["ok"] = True
            return result

    except PlaywrightTimeout as e:
        result["detail"] = f"timeout:{str(e)[:80]}"
        log(f"✗ timeout", tag)
        return result
    except Exception as e:
        result["detail"] = f"err:{str(e)[:80]}"
        log(f"✗ lỗi: {e}", tag)
        return result
    finally:
        result["duration"] = round(time.time() - t0, 2)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


# ============ Batch ============
async def run_batch(usernames: List[str], concurrency: int, hard_timeout: int):
    BATCH_STATE.update({
        "running": True,
        "total": len(usernames),
        "done": 0,
        "failed": 0,
        "started": time.time(),
        "finished": None,
        "elapsed": None,
    })

    sem = asyncio.Semaphore(concurrency)
    t_start = time.time()

    async def worker(idx: int, uname: str):
        if BATCH_STOP.is_set():
            return
        async with sem:
            if time.time() - t_start > hard_timeout:
                log(f"⏱ vượt {hard_timeout}s, bỏ qua", f"#{idx}")
                BATCH_STATE["failed"] += 1
                return
            log(f"▶ bắt đầu ({idx}/{len(usernames)})", f"#{idx}")
            try:
                res = await one_run(uname, idx)
                RUN_HISTORY.append({
                    "idx": idx,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "username": uname,
                    "ok": res["ok"],
                    "step": res["step"],
                    "detail": res["detail"],
                    "duration": res["duration"],
                })
                if res["ok"]:
                    BATCH_STATE["done"] += 1
                else:
                    BATCH_STATE["failed"] += 1
                log(f"■ xong ({idx}) ok={res['ok']} {res['duration']}s", f"#{idx}")
            except Exception as e:
                BATCH_STATE["failed"] += 1
                log(f"✗ crash: {e}", f"#{idx}")

    tasks = [asyncio.create_task(worker(i, u)) for i, u in enumerate(usernames, 1)]
    await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = round(time.time() - t_start, 2)
    BATCH_STATE.update({
        "running": False,
        "finished": time.time(),
        "elapsed": elapsed,
    })
    log(f"✅ BATCH xong: {BATCH_STATE['done']} ok / "
        f"{BATCH_STATE['failed']} fail trong {elapsed}s")


# ============ Models ============
class BatchRequest(BaseModel):
    username: str
    count: int = 10
    concurrency: int = 2


# ============ Routes ============
@app.get("/", response_class=HTMLResponse)
async def home():
    if HTML_FILE.exists():
        return FileResponse(HTML_FILE, media_type="text/html")
    return HTMLResponse("<h1>index.html not found</h1>", status_code=500)


@app.post("/batch")
async def start_batch(req: BatchRequest):
    global BATCH_TASK
    if BATCH_STATE["running"]:
        raise HTTPException(409, "Đang chạy batch khác")
    if not req.username.strip():
        raise HTTPException(400, "username rỗng")
    if req.count < 1 or req.count > 20:
        raise HTTPException(400, "count phải 1-20")

    BATCH_STOP.clear()
    usernames = [req.username.strip()] * req.count
    conc = min(req.concurrency, MAX_CONCURRENT)
    log(f"═══ START BATCH: {req.count} lần, song song {conc}, timeout {HARD_TIMEOUT}s ═══")
    BATCH_TASK = asyncio.create_task(run_batch(usernames, conc, HARD_TIMEOUT))
    return {"started": True, "count": req.count,
            "concurrency": conc, "hard_timeout": HARD_TIMEOUT}


@app.post("/stop")
async def stop_batch():
    BATCH_STOP.set()
    return {"stopping": True}


@app.get("/status")
async def status():
    st = dict(BATCH_STATE)
    if st["running"] and st["started"]:
        st["elapsed"] = round(time.time() - st["started"], 1)
    return st


@app.get("/history")
async def history():
    return list(RUN_HISTORY)


@app.get("/shots")
async def shots_list():
    return [
        {"idx": s["idx"], "tag": s["tag"], "time": s["time"]}
        for s in LAST_SCREENSHOTS
    ]


@app.get("/shot/{idx}")
async def get_shot(idx: int, tag: str = "final"):
    for s in reversed(LAST_SCREENSHOTS):
        if s["idx"] == idx and s["tag"] == tag:
            return Response(content=s["data"], media_type="image/png")
    raise HTTPException(404, "không có screenshot")


@app.get("/logs", response_class=Response)
async def get_logs():
    return Response("\n".join(LOG_BUFFER),
                    media_type="text/plain; charset=utf-8")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "running": BATCH_STATE["running"]}
