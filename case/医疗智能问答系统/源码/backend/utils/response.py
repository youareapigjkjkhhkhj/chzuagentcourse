#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一响应格式和工具函数
"""

import json
from flask import Response

def success_response(data=None, message="Success", status_code=200):
    """
    统一成功响应格式
    
    Args:
        data: 返回数据
        message: 响应消息
        status_code: HTTP状态码
    
    Returns:
        Response: JSON响应
    """
    response = {
        'success': True,
        'message': message,
        'data': data
    }
    if data is None:
        response.pop('data', None)
    
    return Response(
        response=json.dumps(response, ensure_ascii=False),
        status=status_code,
        mimetype='application/json; charset=utf-8'
    )

def error_response(message="Error", error_code=None, status_code=400, data=None):
    """
    统一错误响应格式
    
    Args:
        message: 错误消息
        error_code: 错误代码
        status_code: HTTP状态码
        data: 附加数据
    
    Returns:
        Response: JSON响应
    """
    response = {
        'success': False,
        'message': message,
        'error_code': error_code
    }
    
    if data is not None:
        response['data'] = data
    
    return Response(
        response=json.dumps(response, ensure_ascii=False),
        status=status_code,
        mimetype='application/json; charset=utf-8'
    )

def validate_required_fields(data, required_fields):
    """
    验证必填字段
    
    Args:
        data: 要验证的数据
        required_fields: 必填字段列表
    
    Returns:
        tuple: (is_valid, missing_fields)
    """
    if not isinstance(data, dict):
        return False, ['数据格式错误']
    
    missing_fields = []
    for field in required_fields:
        if field not in data or data[field] is None or data[field] == '':
            missing_fields.append(field)
    
    return len(missing_fields) == 0, missing_fields