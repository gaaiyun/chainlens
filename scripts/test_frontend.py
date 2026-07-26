"""本地静态前端烟测，供 webapp-testing skill 调用。"""

from __future__ import annotations

import json
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
        desktop.route(
            "**/api/query",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                    "title": "实时融资可见性分析",
                    "findings": [
                        {
                            "text": "发现可核验的融资盲区企业线索。",
                            "evidence_id": "E-LIVE-1",
                        }
                    ],
                    "actions": ["进入企业核验流程。"],
                    "evidence": [
                        {
                            "evidence_id": "E-LIVE-1",
                            "kernel": "credit.HiddenChampion",
                            "claim": "融资盲区线索",
                            "value": 12,
                            "unit": "家",
                        }
                    ],
                    "tables": {
                        "financing_gap": [
                            {"grade": "AA", "融资覆盖率%": 13.25},
                            {"grade": "A", "融资覆盖率%": 2.73},
                        ]
                    },
                    "charts": [
                        {
                            "title": "不同信用等级的公开融资覆盖率",
                            "data_key": "financing_gap",
                            "x": "grade",
                            "y": "融资覆盖率%",
                        }
                    ],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        desktop.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        assert desktop.title() == "ChainLens / 链见"
        assert desktop.locator("h1").inner_text().startswith("把经营痕迹")
        desktop.screenshot(path=str(OUTPUT / "desktop.png"), full_page=True)

        desktop.locator('[data-view="qualification"]').click()
        assert "失效" in desktop.locator("h1").inner_text()
        desktop.fill("#question", "未来一年哪些资质需要续期")
        desktop.locator("#query-form button[type=submit]").click()
        desktop.wait_for_function(
            "document.querySelector('#toast').textContent.includes('已接入实时分析引擎')"
        )
        assert "已接入实时分析引擎" in desktop.locator("#toast").inner_text()
        assert desktop.locator("#page-title").inner_text() == "实时融资可见性分析"
        assert desktop.locator("#chart-title").inner_text() == "不同信用等级的公开融资覆盖率"
        assert desktop.locator("#chart .bar-item").count() == 2
        desktop.screenshot(path=str(OUTPUT / "desktop-live.png"), full_page=True)

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
