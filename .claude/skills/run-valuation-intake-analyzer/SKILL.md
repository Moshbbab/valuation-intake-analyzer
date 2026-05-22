---
name: run-valuation-intake-analyzer
description: Build, run, and drive the Valuation Intake Analyzer. Use when asked to start the app, run its tests, take a screenshot of its UI, upload a document, or interact with the running Streamlit server.
---

A Streamlit web app that extracts intake fields from uploaded valuation documents (PDF, DOCX, TXT). Drive it by launching the dev server, then using Node.js Playwright (pre-installed at `/opt/node22`) against `http://localhost:8501`.

All paths below are relative to the repo root (`/home/user/valuation-intake-analyzer/`).

## Prerequisites

No `apt-get` needed — all dependencies are available in the container. Python packages must be pip-installed once:

```bash
pip install streamlit python-docx PyPDF2 pandas pytest
```

## Setup

No build step. No env vars required.

## Run (agent path)

Start the server in the background:

```bash
pkill -f 'streamlit run' 2>/dev/null; sleep 1
streamlit run streamlit_app.py --server.port 8501 --server.headless true &
echo $! > /tmp/streamlit.pid
timeout 20 bash -c 'until curl -sf http://localhost:8501 >/dev/null; do sleep 1; done'
echo "Server ready"
```

Take a screenshot using Node.js Playwright (chromium is at `/opt/pw-browsers/chromium-1194`):

```bash
node - <<'EOF'
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://localhost:8501/', { timeout: 15000 });
await page.waitForTimeout(4000);
await page.screenshot({ path: '/tmp/streamlit_main.png', fullPage: true });
console.log('Screenshot saved to /tmp/streamlit_main.png');
await browser.close();
EOF
```

Upload a file and verify the analysis runs end-to-end:

```bash
node - <<'EOF'
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import { writeFileSync } from 'fs';

writeFileSync('/tmp/test_valuation.txt', `Property Type: Commercial Office
Property Location: Riyadh, King Fahd Road
Valuation Purpose: Mortgage Financing
Basis of Value: Market Value
Valuation Date: 01 June 2025
Documents Provided: Title Deed, Survey Plan`);

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://localhost:8501/', { timeout: 15000 });
await page.waitForTimeout(4000);
await page.locator('input[type="file"]').setInputFiles('/tmp/test_valuation.txt');
await page.waitForTimeout(6000);
await page.screenshot({ path: '/tmp/streamlit_result.png', fullPage: true });
const text = await page.textContent('body');
console.log('Page content:', text?.substring(0, 600));
await browser.close();
EOF
```

Stop the server:

```bash
kill $(cat /tmp/streamlit.pid) 2>/dev/null
```

## Run (human path)

```bash
streamlit run streamlit_app.py   # → opens http://localhost:8501 in browser. Ctrl-C to stop.
```

## Test

```bash
python -m pytest tests/ -v
```

Expected: 6 tests pass. One deprecation warning about PyPDF2 is expected and harmless.

---

## Gotchas

- **`chromium-browser` is a snap stub** — running `/usr/bin/chromium-browser` prints "requires the chromium snap to be installed." Use the pre-installed Playwright chromium at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` via the Node.js Playwright API instead.
- **Python Playwright version mismatch** — `python -m playwright install` fails because Python playwright wants chromium v1223 but the container has v1194. Use Node.js playwright (`/opt/node22/lib/node_modules/playwright`) which matches the installed binary exactly.
- **Streamlit takes ~4s to render** — the React frontend needs time to load after the server is up. Always `waitForTimeout(4000)` before interacting or screenshotting.
- **`--no-sandbox` is required** — Chromium crashes without it in this container environment. Always pass `args: ['--no-sandbox', '--disable-dev-shm-usage']`.
- **Port already in use** — `pkill -f 'streamlit run'` before restarting; otherwise you get `EADDRINUSE`.

## Troubleshooting

- **`Executable doesn't exist at /opt/pw-browsers/chromium_headless_shell-1223/...`**: You used Python playwright. Switch to `import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs'` in a Node.js script.
- **`Command requires the chromium snap`**: The system `chromium-browser` binary is a stub. Use Playwright as shown above.
- **`DeprecationWarning: PyPDF2 is deprecated`**: Expected, harmless. The app functions correctly.
- **Blank screenshot**: The `waitForTimeout(4000)` was skipped or too short. Increase to 5000ms.
