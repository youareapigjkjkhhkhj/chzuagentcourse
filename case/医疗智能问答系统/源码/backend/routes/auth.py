#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证路由
"""

from flask import Blueprint, request, current_app
from datetime import datetime
from models import User
from utils import (
    success_response, error_response, validate_required_fields,
    generate_token, verify_token
)
from utils.validators import (
    validate_email, validate_password, validate_username
)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    用户注册
    """
    try:
        data = request.get_json()
        
        # 验证必填字段
        is_valid, missing_fields = validate_required_fields(data, [
            'username', 'email', 'password'
        ])
        
        if not is_valid:
            return error_response(
                f"缺少必填字段: {', '.join(missing_fields)}",
                'MISSING_REQUIRED_FIELDS',
                400
            )
        
        username = data['username'].strip()
        email = data['email'].strip().lower()
        password = data['password']
        full_name = data.get('name', data.get('full_name', '')).strip()  # 支持前端的name字段
        phone = data.get('phone', '').strip()
        role = data.get('role', 'doctor')  # 默认为doctor角色，符合前端需求
        department = data.get('department', '').strip()
        title = data.get('title', '').strip()
        hospital = data.get('hospital', '').strip()
        
        # 验证字段格式
        is_valid, error_msg = validate_username(username)
        if not is_valid:
            return error_response(error_msg, 'INVALID_USERNAME', 400)
        
        is_valid, error_msg = validate_email(email)
        if not is_valid:
            return error_response(error_msg, 'INVALID_EMAIL', 400)
        
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            return error_response(error_msg, 'INVALID_PASSWORD', 400)
        
        # 检查用户名和邮箱是否已存在
        if User.query.filter_by(username=username).first():
            return error_response('用户名已存在', 'USERNAME_EXISTS', 400)
        
        if User.query.filter_by(email=email).first():
            return error_response('邮箱已被注册', 'EMAIL_EXISTS', 400)
        
        # 创建新用户
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            phone=phone,
            role=role,
            department=department,
            title=title,
            hospital=hospital,
            is_active=True,
            is_verified=False
        )
        
        user.set_password(password)
        
        # 保存到数据库
        from models.base import db
        db.session.add(user)
        db.session.commit()
        
        # 生成token
        token = generate_token(user.id, user.username)
        
        return success_response({
            'user': user.to_dict(),
            'token': token,
            'expires_in': 24 * 3600  # 24小时
        }, '注册成功', 201)
        
    except Exception as e:
        return error_response(f'注册失败: {str(e)}', 'REGISTER_ERROR', 500)

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    用户登录
    """
    try:
        data = request.get_json()
        
        # 验证必填字段
        is_valid, missing_fields = validate_required_fields(data, [
            'username', 'password'
        ])
        
        if not is_valid:
            return error_response(
                f"缺少必填字段: {', '.join(missing_fields)}",
                'MISSING_REQUIRED_FIELDS',
                400
            )
        
        username = data['username'].strip()
        password = data['password']
        
        # 查找用户（支持用户名或邮箱登录）
        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()
        
        if not user:
            return error_response('用户不存在', 'USER_NOT_FOUND', 404)
        
        if not user.check_password(password):
            return error_response('密码错误', 'INVALID_PASSWORD', 401)
        
        if not user.is_active:
            return error_response('账户已被禁用', 'ACCOUNT_DISABLED', 403)
        
        # 更新最后登录时间
        user.last_login = datetime.utcnow()
        from models.base import db
        db.session.commit()
        
        # 生成token
        token = generate_token(user.id, user.username)
        
        return success_response({
            'user': user.to_dict(),
            'token': token,
            'expires_in': 24 * 3600  # 24小时
        }, '登录成功')
        
    except Exception as e:
        return error_response(f'登录失败: {str(e)}', 'LOGIN_ERROR', 500)

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    用户登出
    """
    # JWT token登出通常通过客户端删除token来实现
    # 服务端可以维护黑名单列表（这里简化处理）
    return success_response(None, '登出成功')

@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """
    刷新token
    """
    try:
        data = request.get_json()
        
        if not data or 'token' not in data:
            return error_response('缺少token', 'MISSING_TOKEN', 400)
        
        old_token = data['token']
        
        # 验证现有token
        payload = verify_token(old_token)
        if not payload:
            return error_response('无效的token', 'INVALID_TOKEN', 401)
        
        # 生成新token
        new_token = generate_token(payload['user_id'], payload['username'])
        
        return success_response({
            'token': new_token,
            'expires_in': 24 * 3600
        }, 'token刷新成功')
        
    except Exception as e:
        return error_response(f'token刷新失败: {str(e)}', 'REFRESH_ERROR', 500)

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """
    获取当前用户信息
    """
    try:
        # 从请求头获取token
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return error_response('缺少认证头', 'MISSING_AUTH_HEADER', 401)
        
        try:
            token = auth_header.split(" ")[1]  # Bearer TOKEN
        except IndexError:
            return error_response('无效的认证格式', 'INVALID_AUTH_FORMAT', 401)
        
        # 验证token
        payload = verify_token(token)
        if not payload:
            return error_response('token已过期或无效', 'INVALID_TOKEN', 401)
        
        # 获取用户信息
        user = User.query.get(payload['user_id'])
        if not user or not user.is_active:
            return error_response('用户不存在或已被禁用', 'USER_INACTIVE', 403)
        
        return success_response({
            'user': user.to_dict()
        }, '获取用户信息成功')
        
    except Exception as e:
        return error_response(f'获取用户信息失败: {str(e)}', 'GET_USER_ERROR', 500)

@auth_bp.route('/verify', methods=['GET'])
def verify_token_endpoint():
    """
    验证token
    """
    try:
        # 从请求头获取token
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return error_response('缺少认证头', 'MISSING_AUTH_HEADER', 401)
        
        try:
            token = auth_header.split(" ")[1]  # Bearer TOKEN
        except IndexError:
            return error_response('无效的认证格式', 'INVALID_AUTH_FORMAT', 401)
        
        # 验证token
        payload = verify_token(token)
        if not payload:
            return error_response('token已过期或无效', 'INVALID_TOKEN', 401)
        
        # 获取用户信息
        user = User.query.get(payload['user_id'])
        if not user or not user.is_active:
            return error_response('用户不存在或已被禁用', 'USER_INACTIVE', 403)
        
        return success_response({
            'user': user.to_dict(),
            'token_valid': True
        }, 'token有效')
        
    except Exception as e:
        return error_response(f'token验证失败: {str(e)}', 'VERIFY_ERROR', 500)