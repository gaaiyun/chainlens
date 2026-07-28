"""Run real-browser acceptance against the deployed GitHub Pages frontend."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

DEFAULT_URL = "https://gaaiyun.github.io/chainlens/"


def collect_browser_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    return errors


def run_query(page: Page, question: str, expected_title: str) -> None:
    page.fill("#question", question)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/query"),
        timeout=180_000,
    ) as response_info:
        page.locator("#query-form button[type=submit]").click()
    response = response_info.value
    if not response.ok:
        raise AssertionError(f"public API returned HTTP {response.status}")
    page.wait_for_function(
        "expected => document.querySelector('#page-title').textContent.includes(expected)",
        arg=expected_title,
        timeout=30_000,
    )
    page.wait_for_function(
        "!document.querySelector('#execution-panel').hidden",
        timeout=10_000,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 ChainLens 公网页面")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--output-dir",
        default=str(Path("data/outputs") / f"public_frontend_{date.today():%Y%m%d}"),
    )
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        desktop_errors = collect_browser_errors(desktop)
        desktop.goto(args.url, wait_until="networkidle")
        assert desktop.locator("#page-title").inner_text() == "智能制造产业自由问数"
        assert desktop.locator("#ask-nav").get_attribute("class").find("is-active") >= 0
        assert desktop.locator(".query-examples button").count() == 3
        desktop.locator(".query-examples button").nth(1).click()
        assert "融资记录" in desktop.locator("#question").input_value()
        run_query(desktop, "按注册资本区间统计企业数量", "注册资本区间")
        assert desktop.locator("#chart .bar-item").count() == 5
        assert desktop.locator("#result-table tbody tr").count() == 5
        desktop.locator("#sql-details summary").click()
        assert "v_enterprise" in desktop.locator("#safe-sql").inner_text()
        assert "LIMIT" in desktop.locator("#safe-sql").inner_text()
        assert desktop.locator("#trace-list li").count() >= 6
        with desktop.expect_download() as download_info:
            desktop.locator("#download-snapshot").click()
        download = download_info.value
        assert download.suggested_filename.endswith(".md")
        report_path = output / "desktop-report.md"
        download.save_as(str(report_path))
        assert "注册资本" in report_path.read_text(encoding="utf-8")
        desktop.screenshot(path=str(output / "desktop-live.png"), full_page=True)
        assert not desktop_errors, desktop_errors

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile_errors = collect_browser_errors(mobile)
        mobile.goto(args.url, wait_until="networkidle")
        run_query(mobile, "按企业经济类型统计企业数量", "经济类型")
        assert mobile.locator("#chart .bar-item").count() == 5
        assert mobile.locator("#result-table tbody tr").count() == 12
        mobile.locator("#sql-details summary").click()
        assert "econ_kind" in mobile.locator("#safe-sql").inner_text()
        assert mobile.locator("#trace-list li").count() >= 6
        mobile.screenshot(path=str(output / "mobile-live.png"), full_page=True)
        assert not mobile_errors, mobile_errors

        browser.close()

    print(f"[OK] public desktop/mobile frontend passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
