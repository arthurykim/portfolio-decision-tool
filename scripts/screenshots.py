"""Capture README screenshots of each app view via Playwright + installed Chrome.

Run against a locally running server (task dev). One-off tooling, not shipped.
"""
import pathlib

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = pathlib.Path(__file__).parent.parent / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            color_scheme="dark",
        )
        # The sticky top bar otherwise paints over the top of element captures.
        context.add_init_script(
            "document.addEventListener('DOMContentLoaded',()=>{"
            "const s=document.createElement('style');"
            "s.textContent='.topbar{position:static !important}';"
            "document.head.appendChild(s);});"
        )
        page = context.new_page()

        # --- Markets: dashboard hero (grid + price chart) ---
        page.goto(f"{BASE}/#markets")
        page.wait_for_selector("#fund-grid .fund-card, #fund-grid > *")
        page.wait_for_selector("#main-chart svg", timeout=15000)
        page.wait_for_timeout(600)
        page.locator('div[data-view="markets"] .section').first.screenshot(
            path=str(OUT / "dashboard.png")
        )

        # --- Backtest: apply a preset and run it ---
        page.goto(f"{BASE}/#backtest")
        page.wait_for_selector("#presets button")
        page.get_by_role("button", name="All Weather").click()
        page.get_by_role("button", name="Run backtest").click()
        page.wait_for_selector("#equity-chart svg", timeout=15000)
        page.wait_for_timeout(600)
        page.locator('div[data-view="backtest"] .layout').screenshot(
            path=str(OUT / "backtest.png")
        )

        # --- Assistant: ask a question, wait for the grounded answer ---
        page.goto(f"{BASE}/#assistant")
        page.wait_for_selector("#chat-input")
        page.fill("#chat-input", "What is max drawdown?")
        page.get_by_role("button", name="Send").click()
        page.wait_for_function(
            "!document.getElementById('chat-log').textContent.includes('Thinking')"
            " && document.getElementById('chat-log').textContent.length > 80",
            timeout=15000,
        )
        page.wait_for_timeout(400)
        page.locator('div[data-view="assistant"] .panel').screenshot(
            path=str(OUT / "assistant.png")
        )

        # --- Learn: topic tiles ---
        page.goto(f"{BASE}/#learn")
        page.wait_for_selector("#learn-tiles .learn-tile")
        page.wait_for_timeout(400)
        page.locator('div[data-view="learn"] .section').screenshot(
            path=str(OUT / "learn.png")
        )

        browser.close()
        print("done")


if __name__ == "__main__":
    main()
