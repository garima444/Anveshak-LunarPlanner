/**
 * debug_e2e.js — quick debug of form submission flow
 */
const { chromium } = require('playwright');
const path = require('path');
const fs   = require('fs');

const BASE_URL = 'http://127.0.0.1:8765';
const OUT_DIR  = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx     = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page    = await ctx.newPage();

  // Capture ALL console messages and page errors
  const logs = [];
  page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => logs.push(`[PAGEERROR] ${err.message}`));
  page.on('response', resp => {
    if (resp.url().includes('/analyze') || resp.url().includes('/demo')) {
      logs.push(`[FETCH] ${resp.url()} → ${resp.status()}`);
    }
  });

  console.log('Loading page…');
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

  // Wait for presets
  await page.waitForFunction(() => {
    const g = document.getElementById('preset-group');
    return g && g.querySelectorAll('button').length > 0;
  }, null, { timeout: 10000 });

  // Apply VIPER
  const viperBtn = page.locator('button[data-preset="viper"]');
  if (await viperBtn.count() > 0) await viperBtn.click();
  else {
    const btns = page.locator('#preset-group button');
    const n = await btns.count();
    for (let i = 0; i < n; i++) {
      const txt = await btns.nth(i).textContent();
      if (txt.toLowerCase().includes('viper')) { await btns.nth(i).click(); break; }
    }
  }
  await new Promise(r => setTimeout(r, 500));

  // Set n_results = 3 (faster)
  await page.locator('[name="n_results"]').selectOption('3');

  // DON'T enable focus area (full DEM, no crop — faster)
  // Just use default settings

  // Click Run
  console.log('Submitting form…');
  await page.locator('#run-btn').click();
  await new Promise(r => setTimeout(r, 1000));

  // Screenshot immediately
  await page.screenshot({ path: path.join(OUT_DIR, 'DBG_after_click.png'), fullPage: false });

  // Check status
  const statusEl = await page.locator('#form-status').textContent().catch(() => '');
  console.log('Status msg:', statusEl);

  // Wait 30s and check again
  console.log('Waiting 30s for analysis…');
  await new Promise(r => setTimeout(r, 30000));
  await page.screenshot({ path: path.join(OUT_DIR, 'DBG_after_30s.png'), fullPage: false });
  const status2 = await page.locator('#form-status').textContent().catch(() => '');
  console.log('Status after 30s:', status2);

  // Check results-area visibility
  const isVisible = await page.evaluate(() => {
    const el = document.getElementById('results-area');
    return el ? !el.classList.contains('hidden') : 'element not found';
  });
  console.log('results-area visible:', isVisible);

  // Wait more
  console.log('Waiting another 90s…');
  await new Promise(r => setTimeout(r, 90000));
  await page.screenshot({ path: path.join(OUT_DIR, 'DBG_after_120s.png'), fullPage: false });
  const status3 = await page.locator('#form-status').textContent().catch(() => '');
  console.log('Status after 120s total:', status3);
  const isVis2 = await page.evaluate(() => {
    const el = document.getElementById('results-area');
    return el ? !el.classList.contains('hidden') : 'element not found';
  });
  console.log('results-area visible:', isVis2);

  console.log('\n=== CONSOLE LOGS ===');
  logs.forEach(l => console.log(l));

  await browser.close();
})().catch(err => console.error('FATAL:', err));
