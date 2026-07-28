"""本地静态前端烟测，供 webapp-testing skill 调用。"""

from __future__ import annotations

import json
import os
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
                    "intent": "autonomous",
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
                    "sql": "SELECT grade, enterprise_count FROM financing_gap",
                    "safe_sql": "SELECT grade, enterprise_count FROM financing_gap LIMIT 500",
                    "safety": {
                        "is_safe": True,
                        "errors": [],
                        "modifications": ["自动添加 LIMIT 500"],
                    },
                    "trace": [
                        {"agent": "SQLGenerationAgent", "status": "passed", "detail": "生成 SQL"},
                        {"agent": "SQLSafetyAgent", "status": "passed", "detail": "安全校验通过"},
                    ],
                    "report_markdown": "# 实时融资可见性分析\n\n确定性报告正文。",
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
        assert desktop.locator("#execution-panel").is_visible()
        desktop.locator("#sql-details summary").click()
        assert "LIMIT 500" in desktop.locator("#safe-sql").inner_text()
        assert desktop.locator("#trace-list li").count() == 2
        desktop.screenshot(path=str(OUTPUT / "desktop-live.png"), full_page=True)

        with desktop.expect_download() as download_info:
            desktop.locator("#download-snapshot").click()
        download = download_info.value
        assert download.suggested_filename.endswith(".md")
        download.save_as(str(OUTPUT / "autonomous-report.md"))

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.route(
            "**/api/query",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "title": "智能制造区域产业健康分析",
                        "intent": "autonomous",
                        "findings": [
                            {"text": "区域健康指数已计算。", "evidence_id": "E-REGION-1"}
                        ],
                        "actions": ["进入区域核验流程。"],
                        "evidence": [
                            {
                                "evidence_id": "E-REGION-1",
                                "kernel": "region.Health",
                                "claim": "区域健康指数",
                                "value": 6,
                                "unit": "个",
                            }
                        ],
                        "tables": {
                            "district_health": [
                                {"区县": "潮州市湘桥区", "产业健康指数": 93.8},
                                {"区县": "广州市海珠区", "产业健康指数": 89.9},
                                {"区县": "韶关市武江区", "产业健康指数": 88.5},
                                {"区县": "广州市荔湾区", "产业健康指数": 88.4},
                                {"区县": "茂名市电白区", "产业健康指数": 87.8},
                                {"区县": "广州市天河区", "产业健康指数": 87.2},
                            ]
                        },
                        "charts": [
                            {
                                "title": "区县产业健康指数",
                                "data_key": "district_health",
                                "x": "区县",
                                "y": "产业健康指数",
                            }
                        ],
                        "sql": "SELECT 区县, 产业健康指数 FROM district_health",
                        "safe_sql": "SELECT 区县, 产业健康指数 FROM district_health LIMIT 500",
                        "safety": {"is_safe": True, "errors": [], "modifications": ["自动添加 LIMIT 500"]},
                        "trace": [{"agent": "SQLSafetyAgent", "status": "passed", "detail": "安全校验通过"}],
                        "report_markdown": "# 智能制造区域产业健康分析",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        mobile.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        assert mobile.locator(".primary-nav").is_visible()
        assert mobile.locator("h1").is_visible()
        mobile.fill("#question", "哪些区县产业健康指数较高")
        mobile.locator("#query-form button[type=submit]").click()
        mobile.wait_for_function(
            "document.querySelector('#toast').textContent.includes('已接入实时分析引擎')"
        )
        assert mobile.locator("#chart .bar-item").count() == 5
        assert all(
            len(label) <= 4
            for label in mobile.locator("#chart .bar-label").all_inner_texts()
        )
        mobile.screenshot(path=str(OUTPUT / "mobile.png"), full_page=True)

        error_page = browser.new_page(viewport={"width": 1280, "height": 800})
        error_page.route(
            "**/api/query",
            lambda route: route.fulfill(
                status=422,
                content_type="application/json",
                body=json.dumps(
                    {
                        "error": "SQL 安全校验连续失败",
                        "error_type": "autonomous_analysis_failed",
                        "trace": [],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        error_page.goto(f"http://127.0.0.1:{PORT}", wait_until="networkidle")
        error_page.fill("#question", "危险问题")
        error_page.locator("#query-form button[type=submit]").click()
        error_page.wait_for_function(
            "!document.querySelector('#error-panel').hidden"
        )
        assert "SQL 安全校验连续失败" in error_page.locator("#error-message").inner_text()
        browser.close()
    print(f"[OK] frontend smoke passed: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
