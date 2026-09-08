#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据验证器
"""

import re
# 兼容处理：在缺少 email-validator 依赖时使用轻量回退，避免后端无法启动
try:
    from email_validator import validate_email as validate_email_core, EmailNotValidError
    _EMAIL_VALIDATOR_AVAILABLE = True
except Exception:  # 包含 ModuleNotFoundError 等
    _EMAIL_VALIDATOR_AVAILABLE = False

    class EmailNotValidError(Exception):
        pass

    def validate_email_core(email: str):
        # 简单邮箱格式校验（回退）：确保 basic pattern，避免阻塞注册
        # 说明：这是最低限度的格式校验，不做 DNS/MX 检查
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not isinstance(email, str) or not re.match(pattern, email):
            raise EmailNotValidError("邮箱格式不正确")

def validate_email(email):
    """
    验证邮箱格式
    
    Args:
        email: 邮箱地址
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not email:
        return False, "邮箱不能为空"
    
    try:
        validate_email_core(email)
        return True, None
    except Exception as e:
        # 当依赖缺失时，回退的 validate_email_core 会抛出 EmailNotValidError（自定义）
        return False, str(e)

def validate_phone(phone):
    """
    验证手机号格式（中国大陆）
    
    Args:
        phone: 手机号
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not phone:
        return True, None  # 手机号可选
    
    # 中国大陆手机号正则表达式
    pattern = r'^1[3-9]\d{9}$'
    if re.match(pattern, phone):
        return True, None
    else:
        return False, "请输入有效的手机号"

def validate_password(password):
    """
    验证密码强度
    
    Args:
        password: 密码
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not password:
        return False, "密码不能为空"
    
    if len(password) < 6:
        return False, "密码长度至少6位"
    
    if len(password) > 50:
        return False, "密码长度不能超过50位"
    
    return True, None

def validate_username(username):
    """
    验证用户名格式
    
    Args:
        username: 用户名
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not username:
        return False, "用户名不能为空"
    
    if len(username) < 3:
        return False, "用户名长度至少3位"
    
    if len(username) > 30:
        return False, "用户名长度不能超过30位"
    
    # 只能包含字母、数字、下划线
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "用户名只能包含字母、数字和下划线"
    
    return True, None

def validate_role(role):
    """
    验证用户角色
    
    Args:
        role: 用户角色
    
    Returns:
        tuple: (is_valid, error_message)
    """
    valid_roles = ['admin', 'doctor']  # 前端只使用admin和doctor角色
    if role not in valid_roles:
        return False, f"角色必须是以下之一: {', '.join(valid_roles)}"
    
    return True, None

def validate_model_data(data):
    """
    验证模型配置数据
    
    Args:
        data: 模型配置数据
    
    Returns:
        dict: 验证错误信息字典
    """
    errors = {}
    
    if not isinstance(data, dict):
        errors['data'] = '数据格式错误'
        return errors
    
    # 必填字段验证
    required_fields = ['name', 'provider', 'type', 'modelName']
    for field in required_fields:
        value = data.get(field)
        if value is None:
            errors[field] = f'{field}不能为空'
        elif isinstance(value, dict):
            errors[field] = f'{field}不能是字典类型'
        elif isinstance(value, str) and value.strip() == '':
            errors[field] = f'{field}不能为空'
        elif not isinstance(value, str):
            errors[field] = f'{field}必须是字符串类型'
    
    # 验证模型提供商
    if data.get('provider'):
        valid_providers = ['OPENAI', 'OLLAMA', 'QIANWEN']
        provider = data['provider']
        if isinstance(provider, str):
            provider = provider.upper()
            if provider not in valid_providers:
                errors['provider'] = f'模型提供商必须是以下之一: {", ".join(valid_providers)}'
        else:
            errors['provider'] = '模型提供商必须是字符串类型'
    
    # 验证模型类型
    if data.get('type'):
        valid_types = ['chat', 'embedding']
        model_type = data['type']
        if isinstance(model_type, str):
            if model_type not in valid_types:
                errors['type'] = f'模型类型必须是以下之一: {", ".join(valid_types)}'
        else:
            errors['type'] = '模型类型必须是字符串类型'
    
    # 验证API端点URL
    if data.get('apiEndpoint'):
        api_endpoint = data['apiEndpoint']
        if isinstance(api_endpoint, str):
            api_endpoint = api_endpoint.strip()
            # 更严格的URL验证正则表达式
            url_pattern = r'^https?:\/\/(?:[-\w.])+(?:[:\d]+)?(?:\/(?:[\w\/_~%:]*[\w~%])?)*(?:\?(?:[\w&=%.\-?]+)*)?(?:#(?:[\w\-%.]+)?)*$'
            if not re.match(url_pattern, api_endpoint):
                errors['apiEndpoint'] = 'API端点必须是有效的URL格式'
        else:
            errors['apiEndpoint'] = 'API端点必须是字符串类型'
    
    # 验证数值字段
    if data.get('temperature') is not None:
        temperature = data['temperature']
        if isinstance(temperature, (int, float, str)):
            try:
                temp = float(temperature)
                if not (0 <= temp <= 2):
                    errors['temperature'] = '温度值必须在0-2之间'
            except (ValueError, TypeError):
                errors['temperature'] = '温度值必须是数字'
        else:
            errors['temperature'] = '温度值必须是数字'
    
    if data.get('maxTokens') is not None:
        max_tokens = data['maxTokens']
        if isinstance(max_tokens, (int, str)):
            try:
                tokens = int(max_tokens)
                if not (1 <= tokens <= 32000):
                    errors['maxTokens'] = '最大令牌数必须在1-32000之间'
            except (ValueError, TypeError):
                errors['maxTokens'] = '最大令牌数必须是整数'
        else:
            errors['maxTokens'] = '最大令牌数必须是整数'
    
    if data.get('topP') is not None:
        top_p = data['topP']
        if isinstance(top_p, (int, float, str)):
            try:
                p = float(top_p)
                if not (0 <= p <= 1):
                    errors['topP'] = 'topP值必须在0-1之间'
            except (ValueError, TypeError):
                errors['topP'] = 'topP值必须是数字'
        else:
            errors['topP'] = 'topP值必须是数字'
    
    # 验证字符串长度
    if data.get('name'):
        name = data['name']
        if isinstance(name, str):
            if len(name.strip()) > 50:
                errors['name'] = '模型名称不能超过50个字符'
        else:
            errors['name'] = '模型名称必须是字符串类型'
    
    if data.get('description'):
        description = data['description']
        if isinstance(description, str):
            if len(description) > 500:
                errors['description'] = '描述不能超过500个字符'
        else:
            errors['description'] = '描述必须是字符串类型'
    
    if data.get('systemPrompt'):
        system_prompt = data['systemPrompt']
        if isinstance(system_prompt, str):
            if len(system_prompt) > 2000:
                errors['systemPrompt'] = '系统提示不能超过2000个字符'
        else:
            errors['systemPrompt'] = '系统提示必须是字符串类型'
    
    return errors