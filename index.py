import asyncio
import os
import random
import sys
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


async def garena_automation(username: str):
    async with async_playwright() as p:
        # Render = container Linux headless → bắt buộc các flag này
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
            viewport={"width": 1920, "height": 1080},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )

        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        page = await context.new_page()

        try:
            print("→ Đang mở trang recovery...")
            await page.goto(
                "https://account.garena.com/recovery?locale=vi-VN#/",
                wait_until="networkidle",
                timeout=60000,
            )

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
                print(f"✓ Đã nhập tài khoản: {username}")
            except PlaywrightTimeout:
                print("✗ Không tìm thấy ô nhập tài khoản")
                await page.screenshot(path="/tmp/error_username.png")
                return

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
                print("✓ Đã nhấn nút Tiếp theo")
            except PlaywrightTimeout:
                print("✗ Không tìm thấy nút Tiếp theo")
                await page.screenshot(path="/tmp/error_nextbtn.png")
                return

            # 3. Đợi form xác minh
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # 4. Mã random
            random_code = "".join(str(random.randint(0, 9)) for _ in range(6))
            print(f"→ Mã random: {random_code}")

            try:
                code_inputs = await page.query_selector_all(
                    'input[maxlength="1"], '
                    'input[type="tel"], '
                    'input[autocomplete="one-time-code"]'
                )
                if len(code_inputs) >= 6:
                    for i, digit in enumerate(random_code):
                        await code_inputs[i].fill(digit)
                        await asyncio.sleep(random.uniform(0.1, 0.25))
                    print("✓ Đã điền mã vào 6 ô")
                elif len(code_inputs) >= 1:
                    await code_inputs[0].fill(random_code)
                    print("✓ Đã điền mã vào 1 ô")
                else:
                    print("! Không tìm thấy ô nhập mã (captcha/OTP?)")
            except Exception as e:
                print(f"✗ Lỗi điền mã: {e}")

            # 5. Lưu screenshot + HTML debug (Render cho ghi /tmp)
            await page.screenshot(path="/tmp/garena_result.png", full_page=True)
            with open("/tmp/garena_page.html", "w", encoding="utf-8") as f:
                f.write(await page.content())
            print("✓ Đã lưu /tmp/garena_result.png và /tmp/garena_page.html")

        except PlaywrightTimeout as e:
            print(f"✗ Timeout: {e}")
            try:
                await page.screenshot(path="/tmp/garena_timeout.png")
            except Exception:
                pass
        except Exception as e:
            print(f"✗ Lỗi: {e}")
        finally:
            await browser.close()


def main():
    username = os.getenv("GARENA_USERNAME", "").strip()
    if not username:
        print("✗ Thiếu biến môi trường GARENA_USERNAME")
        sys.exit(1)

    asyncio.run(garena_automation(username))


if __name__ == "__main__":
    main()
