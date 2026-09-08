import asyncio
import html
import os
import re
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def safe_filename(topic):
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", topic.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned[:80] or "research_report"


def _resolve_output_dir(output_dir=None):
    target = Path(output_dir or "generated_reports")
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_report(report, topic, output_dir=None, filename_base=None):
    """
    保存报告为 Markdown 文件。
    """
    output_path = _resolve_output_dir(output_dir)
    base = filename_base or safe_filename(topic)
    filename = output_path / f"{base}_report.md"
    with open(filename, "w", encoding="utf-8") as file:
        file.write(report)
    print(f"Markdown report saved as {filename}")
    return str(filename.resolve())


def _markdown_extensions():
    extensions = ["extra", "tables", "fenced_code", "codehilite"]
    try:
        import mdx_math  # noqa: F401
        extensions.append("mdx_math")
    except Exception:
        pass
    return extensions


def save_pdf(report, topic, output_dir=None, filename_base=None):
    """
    直接从 report 字符串生成 PDF：Markdown → HTML → Playwright PDF。
    """
    output_path = _resolve_output_dir(output_dir)
    base = filename_base or safe_filename(topic)
    pdf_filename = output_path / f"{base}_report.pdf"
    html_filename = output_path / f"{base}_report_temp.html"

    try:
        html_content = markdown.markdown(report, extensions=_markdown_extensions())
        escaped_title = html.escape(f"{topic} Report")
        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #2f3437;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        h1, h2, h3 {{ color: #15191d; }}
        h1 {{ border-bottom: 2px solid #d8ece8; padding-bottom: 12px; }}
        a {{ color: #0f766e; }}
        pre {{
            background: #f6f8fa;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.95em;
        }}
        code {{ font-family: Consolas, "Courier New", monospace; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
        img {{ max-width: 100%; height: auto; }}
        ul, ol {{ padding-left: 20px; }}
    </style>
</head>
<body>
    {html_content}
</body>
</html>"""

        with open(html_filename, "w", encoding="utf-8") as file:
            file.write(full_html)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            file_url = f"file:///{os.path.abspath(html_filename).replace(os.sep, '/')}"
            page.goto(file_url, wait_until="networkidle")
            page.wait_for_timeout(1500)

            page.pdf(
                path=str(pdf_filename),
                format="A4",
                print_background=True,
                margin={
                    "top": "20mm",
                    "bottom": "20mm",
                    "left": "15mm",
                    "right": "15mm",
                },
                scale=1.0,
                prefer_css_page_size=True,
            )
            browser.close()

        print(f"PDF report saved as {pdf_filename}")
        return str(pdf_filename.resolve())

    except Exception as exc:
        print(f"生成 PDF 失败: {exc}")
        raise

    finally:
        if os.path.exists(html_filename):
            os.remove(html_filename)
