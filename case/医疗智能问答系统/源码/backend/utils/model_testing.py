#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型连接真实测试工具

针对不同provider执行最小化的真实HTTP请求，验证endpoint与凭证是否可用。
返回统一测试结果结构：
{
  'success': bool,
  'responseTime': float | None,
  'errorMessage': str | None,
  'sampleResponse': str | None
}
"""

from __future__ import annotations
import time
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import requests
from requests.exceptions import RequestException, Timeout


def _time_call(func):
    start = time.perf_counter()
    try:
        result = func()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return result, round(elapsed_ms, 2), None
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return None, round(elapsed_ms, 2), e


def _normalize_base(url: Optional[str], default: str) -> str:
    """通用基础URL规范化：去除末尾/。不处理路径深度。"""
    if not url:
        return default.rstrip('/')
    return url.rstrip('/')


def _derive_openai_v1_base(api_endpoint: Optional[str]) -> str:
    """根据传入的OpenAI端点推导出 /v1 基础路径。

    兼容以下形式：
    - https://api.openai.com/v1
    - https://api.openai.com/v1/chat/completions
    - https://api.chatanywhere.tech
    - https://api.chatanywhere.tech/v1

    规则：
    - 若未提供，返回 https://api.openai.com/v1
    - 若路径中包含 /v1，则截断到 /v1（包含）
    - 否则，在域名后追加 /v1
    """
    if not api_endpoint:
        return 'https://api.openai.com/v1'

    parsed = urlparse(api_endpoint)
    # 无scheme或netloc时，回退默认
    if not parsed.scheme or not parsed.netloc:
        return 'https://api.openai.com/v1'

    path = parsed.path or ''
    v1_index = path.find('/v1')
    if v1_index != -1:
        # 截断到 /v1
        base_path = path[:v1_index + len('/v1')]
    else:
        base_path = '/v1'

    return f"{parsed.scheme}://{parsed.netloc}{base_path}".rstrip('/')


def test_openai(api_endpoint: Optional[str], api_key: Optional[str], model_name: Optional[str]) -> Dict[str, Any]:
    # 通过传入的端点推导 /v1 基础路径，避免出现 /chat/completions/models 导致404
    base = _derive_openai_v1_base(api_endpoint)
    url = f"{base}/models"
    headers = {
        'Authorization': f'Bearer {api_key}' if api_key else '',
        'Accept': 'application/json'
    }

    if not api_key:
        return {
            'success': False,
            'responseTime': None,
            'errorMessage': '缺少apiKey，无法验证OpenAI连接',
            'sampleResponse': None,
        }

    def call():
        return requests.get(url, headers=headers, timeout=6)

    resp, elapsed, err = _time_call(call)
    if err:
        return {
            'success': False,
            'responseTime': elapsed,
            'errorMessage': f'请求失败: {str(err)}',
            'sampleResponse': None,
        }

    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code == 200 and isinstance(data, dict):
        # 如果指定了模型名，尝试检查是否存在
        exists = True
        if model_name and isinstance(data.get('data'), list):
            exists = any((item.get('id') == model_name) for item in data['data'])
        return {
            'success': exists,
            'responseTime': elapsed,
            'errorMessage': None if exists else f'模型{model_name}不可用或不存在',
            'sampleResponse': f"models_count={len(data.get('data', []))}",
        }
    else:
        return {
            'success': False,
            'responseTime': elapsed,
            'errorMessage': f'HTTP {resp.status_code}: {resp.text[:200]}',
            'sampleResponse': None,
        }


def test_ollama(api_endpoint: Optional[str], model_name: Optional[str]) -> Dict[str, Any]:
    base = _normalize_base(api_endpoint, 'http://localhost:11434')
    url = f"{base}/api/tags"

    def call():
        return requests.get(url, timeout=5)

    resp, elapsed, err = _time_call(call)
    if err:
        return {
            'success': False,
            'responseTime': elapsed,
            'errorMessage': f'请求失败: {str(err)}',
            'sampleResponse': None,
        }

    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code == 200 and isinstance(data, dict):
        models = [m.get('name') for m in data.get('models', []) if isinstance(m, dict)]
        exists = True if not model_name else (model_name in models)
        return {
            'success': exists,
            'responseTime': elapsed,
            'errorMessage': None if exists else f'模型{model_name}未在Ollama中加载',
            'sampleResponse': f"models={models[:5]}",
        }
    else:
        return {
            'success': False,
            'responseTime': elapsed,
            'errorMessage': f'HTTP {resp.status_code}: {resp.text[:200]}',
            'sampleResponse': None,
        }


def test_qianwen(api_endpoint: Optional[str], api_key: Optional[str], model_name: Optional[str]) -> Dict[str, Any]:
    # DashScope最小文本生成请求
    base = _normalize_base(api_endpoint, 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation')
    url = base
    headers = {
        'Authorization': f'Bearer {api_key}' if api_key else '',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if not api_key:
        return {
            'success': False,
            'responseTime': None,
            'errorMessage': '缺少apiKey，无法验证千问连接',
            'sampleResponse': None,
        }

    payload = {
        'model': model_name or 'qwen-turbo',
        'input': {
            'messages': [
                {'role': 'user', 'content': 'ping'}
            ]
        },
        'parameters': {
            'max_tokens': 1
        }
    }

    def call():
        return requests.post(url, headers=headers, json=payload, timeout=8)

    resp, elapsed, err = _time_call(call)
    if err:
        return {
            'success': False,
            'responseTime': elapsed,
            'errorMessage': f'请求失败: {str(err)}',
            'sampleResponse': None,
        }

    # DashScope成功通常返回200/201并包含output或choices
    ok = resp.status_code in (200, 201)
    sample = None
    try:
        data = resp.json()
        sample = str(data)[:200]
    except Exception:
        data = None

    return {
        'success': ok,
        'responseTime': elapsed,
        'errorMessage': None if ok else f'HTTP {resp.status_code}: {resp.text[:200]}',
        'sampleResponse': sample,
    }


def test_model_connection(model) -> Dict[str, Any]:
    """根据provider执行真实测试"""
    provider = (model.provider or '').strip().lower()
    if provider == 'openai':
        return test_openai(model.api_endpoint, model.api_key, model.model_name)
    elif provider == 'ollama':
        return test_ollama(model.api_endpoint, model.model_name)
    elif provider == 'qianwen':
        return test_qianwen(model.api_endpoint, model.api_key, model.model_name)
    else:
        return {
            'success': False,
            'responseTime': None,
            'errorMessage': f'未知的provider: {model.provider}',
            'sampleResponse': None,
        }