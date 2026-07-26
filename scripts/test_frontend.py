"""本地静态前端烟测，供 webapp-testing skill 调用。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "outputs" / "frontend_smoke"
OUTPUT.mkdir(parents=True, exist_ok=True)
PORT = os.environ.get("CHAINLENS_FRONTEND_PORT", "4173")


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        desktop.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        assert desktop.title() == "ChainLens / 链见"
        assert desktop.locator("h1").inner_text().startswith("把经营痕迹")
        desktop.screenshot(path=str(OUTPUT / "desktop.png"), full_page=True)

        desktop.locator('[data-view="qualification"]').click()
        assert "失效" in desktop.locator("h1").inner_text()
        desktop.fill("#question", "未来一年哪些资质需要续期")
        desktop.locator("#query-form button[type=submit]").click()
        assert "当前为聚合快照" in desktop.locator("#toast").inner_text()

        with desktop.expect_download() as download_info:
            desktop.locator("#download-snapshot").click()
        download = download_info.value
        download.save_as(str(OUTPUT / "qualification-snapshot.json"))

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        assert mobile.locator(".primary-nav").is_visible()
        assert mobile.locator("h1").is_visible()
        mobile.screenshot(path=str(OUTPUT / "mobile.png"), full_page=True)
        browser.close()
    print(f"[OK] frontend smoke passed: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
