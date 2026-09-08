#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证工具函数
"""

import jwt
import datetime
from functools import wraps
from flask import request, jsonify, current_app
from .response import error_response

def generate_token(user_id, username):
    """
    生成JWT token
    
    Args:
        user_id: 用户ID
        username: 用户名
    
    Returns:
        str: JWT token
    """
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow()
    }
    
    token = jwt.encode(
        payload, 
        current_app.config['SECRET_KEY'], 
        algorithm='HS256'
    )
    return token

def verify_token(token):
    """
    验证JWT token
    
    Args:
        token: JWT token
    
    Returns:
        dict: 解码后的用户信息
    """
    try:
        payload = jwt.decode(
            token, 
            current_app.config['SECRET_KEY'], 
            algorithms=['HS256']
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def login_required(f):
    """
    登录要求装饰器
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # 从请求头中获取token
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer TOKEN
            except IndexError:
                return error_response('无效的认证格式', 'INVALID_AUTH_FORMAT', 401)
        
        if not token:
            return error_response('缺少认证token', 'MISSING_TOKEN', 401)
        
        # 验证token
        payload = verify_token(token)
        if not payload:
            return error_response('token已过期或无效', 'INVALID_TOKEN', 401)
        
        # 将用户信息添加到请求上下文
        request.current_user = {
            'user_id': payload['user_id'],
            'username': payload['username']
        }
        
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """
    获取当前登录用户信息
    
    Returns:
        dict: 用户信息字典，如果未登录则返回None
    """
    if hasattr(request, 'current_user'):
        return request.current_user
    return None

# 保持向后兼容的别名
token_required = login_required

def admin_required(f):
    """
    管理员权限要求装饰器
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import User
        
        # 先检查登录
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return error_response('无效的认证格式', 'INVALID_AUTH_FORMAT', 401)
        
        if not token:
            return error_response('缺少认证token', 'MISSING_TOKEN', 401)
        
        payload = verify_token(token)
        if not payload:
            return error_response('token已过期或无效', 'INVALID_TOKEN', 401)
        
        # 检查用户权限
        user = User.query.get(payload['user_id'])
        if not user or not user.is_active:
            return error_response('用户不存在或已被禁用', 'USER_INACTIVE', 403)
        
        if user.role != 'admin':
            return error_response('需要管理员权限', 'ADMIN_REQUIRED', 403)
        
        request.current_user = {
            'user_id': payload['user_id'],
            'username': payload['username'],
            'role': user.role
        }
        
        return f(*args, **kwargs)
    
    return decorated_function