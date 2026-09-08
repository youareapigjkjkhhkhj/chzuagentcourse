import os
import tempfile

import pdfplumber
import requests


def _download_with_proxy_fallback(url, timeout=20):
    errors = []

    for trust_env in (True, False):
        session = requests.Session()
        session.trust_env = trust_env
        try:
            return session.get(url, timeout=timeout)
        except Exception as exc:
            mode = "system proxy/env" if trust_env else "direct/no proxy"
            message = f"PDF download failed with {mode}: {exc}"
            print(f"[警告] {message}")
            errors.append(message)

    raise requests.ConnectionError("; ".join(errors))


def read_pdf_from_url(url, max_length=3000):
    """
    下载 PDF 并提取文本。

    参数：
    - url: PDF 文件 URL
    - max_length: 返回文本最大长度，避免内存过大

    返回：
    - PDF 文本内容（字符串）或 None（无法读取）
    """
    temp_path = None

    try:
        response = _download_with_proxy_fallback(url, timeout=20)
        if response.status_code != 200:
            print(f"[警告] 下载失败，状态码: {response.status_code}")
            return None

        content_type = response.headers.get("Content-Type", "")
        if "application/pdf" not in content_type and not response.content.startswith(b"%PDF"):
            print(f"[警告] URL 不是 PDF 文件: {url}")
            return None

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as file:
            temp_path = file.name
            file.write(response.content)

        text = ""
        with pdfplumber.open(temp_path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
                if len(text) >= max_length:
                    break

        return text[:max_length]

    except Exception as exc:
        print(f"[警告] 读取 PDF 失败: {exc}")
        return None

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
