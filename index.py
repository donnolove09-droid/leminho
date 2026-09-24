import asyncio
import io
import os
import random
import time
from collections import deque
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

app = FastAPI(title="Garena Bot")

# ============ Lưu log + screenshot trong RAM ============
LOG_BUFFER = deque(maxlen=500)
LAST_SCREENSHOT: bytes | None = None
LAST_RUN_STATUS = {"state": "idle", "started": None, "finished": None, "result": None}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_BUFFER.append(line)


# ============ Core: chạy Playwright ============
async def garena_automation(username: str):
    global LAST_SCREENSHOT
    LAST_RUN_STATUS.update(state="running", started=time.time(), finished=None, result=None)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()

        result = {"ok": False, "step": None, "detail": None}

        try:
            log("→ Mở trang recovery...")
            await page.goto(
                "https://account.garena.com/recovery?locale=vi-VN#/",
                wait_until="networkidle",
                timeout=60000,
            )
            result["step"] = "loaded"

            # 1. Nhập username
            try:
                username_input = await page.wait_for_selector(
                    'input[type="text"], input[name="username"], '
                    'input[placeholder*="Tài khoản"], input[placeholder*="tài khoản"]',
                    timeout=15000,
                    state="visible",
                )
                await username_input.click()
                await username_input.type(username, delay=random.randint(80, 180))
                log(f"✓ Đã nhập tài khoản: {username}")
                result["step"] = "username_filled"
            except PlaywrightTimeout:
                log("✗ Không tìm thấy ô nhập tài khoản")
                result["detail"] = "username_input_not_found"
                return result

            # 2. Nhấn Tiếp theo
            try:
                next_button = await page.wait_for_selector(
                    'button:has-text("Tiếp theo"), '
                    'button:has-text("Next"), '
                    'button[type="submit"]',
                    timeout=10000,
                    state="visible",
                )
                await asyncio.sleep(random.uniform(0.4, 1.2))
                await next_button.click()
                log("✓ Đã nhấn nút Tiếp theo")
                result["step"] = "next_clicked"
            except PlaywrightTimeout:
                log("✗ Không tìm thấy nút Tiếp theo")
                result["detail"] = "next_button_not_found"
                return result

            # 3. Đợi form xác minh
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # 4. Điền mã random (chỉ để test UI)
            random_code = "".join(str(random.randint(0, 9)) for _ in range(6))
            log(f"→ Mã random: {random_code}")
            try:
                code_inputs = await page.query_selector_all(
                    'input[maxlength="1"], input[type="tel"], '
                    'input[autocomplete="one-time-code"]'
                )
                if len(code_inputs) >= 6:
                    for i, digit in enumerate(random_code):
                        await code_inputs[i].fill(digit)
                        await asyncio.sleep(random.uniform(0.1, 0.25))
                    log("✓ Đã điền mã vào 6 ô")
                    result["step"] = "code_filled"
                elif len(code_inputs) >= 1:
                    await code_inputs[0].fill(random_code)
                    log("✓ Đã điền mã vào 1 ô")
                    result["step"] = "code_filled"
                else:
                    log("! Không tìm thấy ô nhập mã (captcha/OTP?)")
                    result["detail"] = "no_code_input"
            except Exception as e:
                log(f"✗ Lỗi điền mã: {e}")

            # 5. Screenshot
            LAST_SCREENSHOT = await page.screenshot(full_page=True)
            log("✓ Đã chụp screenshot")

            # 6. HTML debug
            html = await page.content()
            with open("/tmp/garena_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            log("✓ Đã lưu /tmp/garena_page.html")

            result["ok"] = True
            return result

        except PlaywrightTimeout as e:
            log(f"✗ Timeout: {e}")
            result["detail"] = f"timeout: {e}"
            try:
                LAST_SCREENSHOT = await page.screenshot(full_page=True)
            except Exception:
                pass
            return result
        except Exception as e:
            log(f"✗ Lỗi: {e}")
            result["detail"] = str(e)
            return result
        finally:
            await browser.close()
            LAST_RUN_STATUS.update(
                state="done", finished=time.time(), result=result
            )


# ============ API ============
class RunRequest(BaseModel):
    username: str


@app.get("/", response_class=HTMLResponse)
async def home():
    status = LAST_RUN_STATUS
    logs = "\n".join(LOG_BUFFER) or "(chưa có log)"
    return f"""
    <html><head><title>Garena Bot</title>
    <style>
      body {{ font-family: monospace; background:#111; color:#eee; padding:20px; }}
      input, button {{ padding:8px; font-size:14px; }}
      pre {{ background:#000; padding:12px; border-radius:6px; overflow:auto;
             max-height:400px; }}
      .row {{ margin-bottom:12px; }}
      a {{ color:#6cf; }}
    </style></head>
    <body>
      <h2>Garena Bot — Render Web Service</h2>

      <div class="row">
        <input id="u" placeholder="username" style="width:240px"/>
        <button onclick="run()">Chạy</button>
        <button onclick="location.reload()">Refresh log</button>
      </div>

      <div class="row">
        Trạng thái: <b>{status['state']}</b>
        &nbsp;|&nbsp; <a href="/screenshot" target="_blank">Xem screenshot</a>
        &nbsp;|&nbsp; <a href="/logs" target="_blank">Raw logs</a>
      </div>

      <pre id="log">{logs}</pre>

      <script>
        async function run() {{
          const u = document.getElementById('u').value.trim();
          if (!u) return alert('Nhập username');
          const r = await fetch('/run', {{
            method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{username: u}})
          }});
          const data = await r.json();
          alert('Kết quả: ' + JSON.stringify(data));
          location.reload();
        }}
        // Tự refresh log mỗi 3s
        setInterval(async () => {{
          const r = await fetch('/logs');
          document.getElementById('log').textContent = await r.text();
        }}, 3000);
      </script>
    </body></html>
    """


@app.post("/run")
async def run(req: RunRequest):
    if not req.username.strip():
        raise HTTPException(400, "username rỗng")
    if LAST_RUN_STATUS["state"] == "running":
        raise HTTPException(409, "Đang chạy, đợi xong đã")
    log(f"=== Bắt đầu chạy cho: {req.username} ===")
    result = await garena_automation(req.username.strip())
    log(f"=== Kết thúc: {result} ===")
    return result


@app.get("/logs", response_class=Response)
async def logs():
    return Response("\n".join(LOG_BUFFER), media_type="text/plain; charset=utf-8")


@app.get("/screenshot")
async def screenshot():
    if LAST_SCREENSHOT is None:
        raise HTTPException(404, "Chưa có screenshot")
    return Response(content=LAST_SCREENSHOT, media_type="image/png")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "state": LAST_RUN_STATUS["state"]}
