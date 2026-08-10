"""
capture_landing_screenshots.py — one-off high-res PNG capture for landing.
Uses direct Playwright with device_scale_factor=2 for retina output.
"""
import asyncio, os
from playwright.async_api import async_playwright
from pathlib import Path

OUT = Path("/app/landing_screenshots")
OUT.mkdir(exist_ok=True, parents=True)

VIEWPORT = {"width": 390, "height": 844}
DPR = 3  # 3x for the sharpest possible output


async def dismiss_modals(page):
    """Best-effort — click through common first-open modals."""
    for _ in range(3):
        clicked = False
        for text_ in ["ACCEPT & CONTINUE", "YES, USE THIS", "NOT NOW"]:
            try:
                await page.get_by_text(text_, exact=True).first.click(timeout=800)
                clicked = True
                await page.wait_for_timeout(400)
            except Exception:
                pass
        if not clicked:
            break
    for test_id in ["briefing-close", "perm-later"]:
        try:
            await page.get_by_test_id(test_id).first.click(timeout=800)
            await page.wait_for_timeout(400)
        except Exception:
            pass


async def login(page):
    await page.goto("http://localhost:3000/login", wait_until="domcontentloaded")
    await page.wait_for_selector("input[type='email']", timeout=30000)
    await page.wait_for_timeout(800)
    await page.fill("input[type='email']", "client@crewfit.com")
    await page.fill("input[type='password']", "Client123!")
    await page.get_by_text("SIGN IN", exact=True).click()
    await page.wait_for_timeout(4500)
    await dismiss_modals(page)


async def wait_root_paint(page, min_len=40, timeout=20000):
    await page.wait_for_function(
        f"() => {{ const r = document.getElementById('root'); return r && r.innerText && r.innerText.length > {min_len}; }}",
        timeout=timeout,
    )
    await page.wait_for_timeout(1500)


async def scroll_container_to(page, y):
    """Scroll the outer app scroll container to y."""
    return await page.evaluate(f"""() => {{
        const cs = Array.from(document.querySelectorAll('div'));
        for (const el of cs) {{
            const st = getComputedStyle(el);
            if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 100) {{
                el.scrollTop = {y};
                return true;
            }}
        }}
        return false;
    }}""")


async def shot(page, name):
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False, type="png", omit_background=False)
    print("✓", path.name, os.path.getsize(path)//1024, "KB")


async def capture_01_roster_calendar(page):
    await page.goto("http://localhost:3000/(client)/calendar", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(2500)
    try:
        await page.get_by_text("AUG", exact=True).click(timeout=2000)
        await page.wait_for_timeout(1500)
    except Exception:
        pass
    await shot(page, "01-roster-calendar")


async def capture_02_traffic_light(page):
    await page.goto("http://localhost:3000/(client)/home", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(3500)
    await dismiss_modals(page)
    await scroll_container_to(page, 1650)
    await page.wait_for_timeout(1200)
    await shot(page, "02-traffic-light")


async def capture_03_todays_reality(page):
    await page.goto("http://localhost:3000/(client)/home", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(3000)
    await dismiss_modals(page)
    try:
        await page.get_by_test_id("reality-btn-home").click(timeout=3000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        print("reality btn err:", e)
    await shot(page, "03-todays-reality")


async def capture_04_change_environment(page):
    await page.goto("http://localhost:3000/hotel-setup?date=2026-08-07", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(3000)
    await shot(page, "04-change-environment")


async def capture_05_guided_workout(page):
    # workout id refreshed by seeder on each run — hardcode current one below.
    wid = os.environ.get("WORKOUT_ID", "a7f1ede8-95f4-476b-9f24-f9e8e643545f")
    print("workout id:", wid)
    await page.goto(f"http://localhost:3000/workout/{wid}", wait_until="domcontentloaded")
    try:
        await wait_root_paint(page, timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(8000)
    await shot(page, "05-guided-workout")


async def capture_06_nutrition(page):
    await page.goto("http://localhost:3000/(client)/nutrition", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(3500)
    await shot(page, "06-nutrition")


async def capture_07_airport_mode(page):
    await page.goto("http://localhost:3000/nutrition/airport", wait_until="domcontentloaded")
    await wait_root_paint(page)
    await page.wait_for_timeout(3500)
    await shot(page, "07-airport-mode")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DPR,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        )
        page = await ctx.new_page()
        page.set_default_timeout(30000)

        await login(page)

        await capture_01_roster_calendar(page)
        await capture_02_traffic_light(page)
        await capture_03_todays_reality(page)
        await capture_04_change_environment(page)
        await capture_05_guided_workout(page)
        await capture_06_nutrition(page)
        await capture_07_airport_mode(page)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
