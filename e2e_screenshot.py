"""
e2e_screenshot.py — Anveshak end-to-end Playwright walkthrough
Captures screenshots of: home form, filled form, results page, map, report.
"""
import asyncio, json, os, sys, time
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8765"
OUT_DIR  = Path("screenshots")
OUT_DIR.mkdir(exist_ok=True)

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context(viewport={"width": 1400, "height": 900})
        page    = await ctx.new_page()

        # ── 1. Home page (empty form) ──────────────────────────────────────────
        print("1. Navigating to home page…")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)
        await page.screenshot(path=OUT_DIR / "01_home_page.png", full_page=True)
        print("   ✓ 01_home_page.png")

        # ── 2. Click VIPER preset ──────────────────────────────────────────────
        print("2. Selecting VIPER preset…")
        # Wait for presets to load
        await page.wait_for_selector('[data-preset-id]', timeout=10_000)
        viper_btn = page.locator('[data-preset-id="viper"]')
        if await viper_btn.count() == 0:
            # Try generic button approach
            btns = page.locator('.preset-btn')
            n = await btns.count()
            for i in range(n):
                txt = await btns.nth(i).text_content()
                if 'VIPER' in txt or 'viper' in txt.lower():
                    await btns.nth(i).click()
                    break
        else:
            await viper_btn.click()
        await page.wait_for_timeout(800)
        await page.screenshot(path=OUT_DIR / "02_viper_preset_selected.png", full_page=True)
        print("   ✓ 02_viper_preset_selected.png")

        # ── 3. Set focus area to Shackleton Crater region ─────────────────────
        print("3. Setting focus area (Shackleton Crater, -89.9°lat, 0° lon)…")
        # Fill mission name
        await page.fill('[name="mission_name"]', 'VIPER Demo — Shackleton Rim')
        await page.fill('[name="agency"]', 'NASA')

        # Focus area — latitude bounding box
        focus_lat_min = page.locator('[name="focus_lat_min"]')
        focus_lat_max = page.locator('[name="focus_lat_max"]')
        if await focus_lat_min.count() > 0:
            await focus_lat_min.fill('-89.95')
            await focus_lat_max.fill('-89.7')

        # Focus center approach (circular)
        focus_clat = page.locator('[name="focus_center_lat"]')
        focus_clon = page.locator('[name="focus_center_lon"]')
        focus_r    = page.locator('[name="focus_radius_km"]')
        if await focus_clat.count() > 0:
            await focus_clat.fill('-89.9')
            await focus_clon.fill('0')
            await focus_r.fill('30')

        # PSR intent — rim (VIPER wants to skirt PSR edges)
        psr_sel = page.locator('[name="psr_intent"]')
        if await psr_sel.count() > 0:
            await psr_sel.select_option('rim')

        # n_results
        n_res = page.locator('[name="n_results"]')
        if await n_res.count() > 0:
            await n_res.fill('5')

        await page.screenshot(path=OUT_DIR / "03_form_filled.png", full_page=True)
        print("   ✓ 03_form_filled.png")

        # ── 4. Submit the form ─────────────────────────────────────────────────
        print("4. Submitting mission plan (this may take 15-40 s for terrain scoring)…")
        t0 = time.time()

        # Click the Analyze / Plan button
        submit_btn = page.locator('button[type="submit"], button:has-text("Analyze"), button:has-text("Plan"), #analyze-btn, .analyze-btn')
        await submit_btn.first.click()

        # Wait for results — either a results section or a spinner going away
        try:
            await page.wait_for_selector(
                '#results, .results-section, .site-card, #mission-results, [id*="result"]',
                timeout=90_000,
            )
        except Exception:
            # Fallback: wait for network to be idle
            await page.wait_for_load_state("networkidle", timeout=90_000)

        elapsed = time.time() - t0
        print(f"   Analysis done in {elapsed:.1f} s")

        await page.screenshot(path=OUT_DIR / "04_results_overview.png", full_page=True)
        print("   ✓ 04_results_overview.png")

        # ── 5. Scroll to map section ───────────────────────────────────────────
        print("5. Scrolling to map…")
        map_el = page.locator('.plotly-graph-div, #map-container, #terrain-map, [id*="map"]')
        if await map_el.count() > 0:
            await map_el.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(1000)
            await page.screenshot(path=OUT_DIR / "05_mission_map.png", full_page=False)
            print("   ✓ 05_mission_map.png")
        else:
            await page.screenshot(path=OUT_DIR / "05_mission_map_fullpage.png", full_page=True)
            print("   ✓ 05_mission_map_fullpage.png (map element not isolated)")

        # ── 6. Scroll to score chart / site cards ─────────────────────────────
        print("6. Scrolling to site scoring section…")
        chart_el = page.locator('.site-card, #score-chart, [id*="score"], [id*="site"]')
        if await chart_el.count() > 0:
            await chart_el.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            await page.screenshot(path=OUT_DIR / "06_site_scores.png", full_page=False)
            print("   ✓ 06_site_scores.png")

        # ── 7. Scroll to mission report / text summary ─────────────────────────
        print("7. Scrolling to mission report…")
        report_el = page.locator('#report, .report-section, [id*="report"], .mission-report')
        if await report_el.count() > 0:
            await report_el.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            await page.screenshot(path=OUT_DIR / "07_mission_report.png", full_page=False)
            print("   ✓ 07_mission_report.png")

        # ── 8. Full-page final state ───────────────────────────────────────────
        print("8. Final full-page screenshot of complete results…")
        await page.keyboard.press("Home")
        await page.wait_for_timeout(300)
        await page.screenshot(path=OUT_DIR / "08_full_results.png", full_page=True)
        print("   ✓ 08_full_results.png")

        # ── 9. Also hit /demo endpoint directly as a JSON reference ───────────
        print("9. Capturing JSON demo output…")
        demo_page = await ctx.new_page()
        await demo_page.goto(f"{BASE_URL}/demo", wait_until="networkidle", timeout=60_000)
        demo_content = await demo_page.content()
        # Try to parse the JSON body text
        try:
            demo_json = await demo_page.evaluate("() => document.body.innerText")
            data = json.loads(demo_json)
            with open(OUT_DIR / "demo_response.json", "w") as f:
                json.dump(data, f, indent=2)
            print("   ✓ demo_response.json saved")
        except Exception as e:
            print(f"   ! Could not parse demo JSON: {e}")
        await demo_page.screenshot(path=OUT_DIR / "09_demo_api.png", full_page=True)
        print("   ✓ 09_demo_api.png")

        await browser.close()

    print("\n=== All screenshots saved to ./screenshots/ ===")
    for f in sorted(OUT_DIR.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")

asyncio.run(main())
