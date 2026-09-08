#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户管理路由
"""

from flask import Blueprint, request, send_file
from sqlalchemy import or_
from io import BytesIO
import pandas as pd
from datetime import datetime
from models import User
from utils import (
    success_response, error_response, validate_required_fields, 
    login_required, admin_required
)
from utils.validators import (
    validate_email, validate_password, validate_username, validate_role
)

users_bp = Blueprint('users', __name__)

@users_bp.route('/', methods=['POST'])
@admin_required
def create_user():
    """
    创建新用户（管理员权限）
    """
    try:
        data = request.get_json()
        
        # 验证必填字段
        is_valid, missing_fields = validate_required_fields(data, [
            'username', 'email', 'password', 'name'
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
        name = data['name'].strip()
        role = data.get('role', 'doctor')  # 默认为doctor角色
        
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
            full_name=name,
            role=role,
            is_active=True,
            is_verified=False
        )
        
        user.set_password(password)
        
        # 保存到数据库
        from models.base import db
        db.session.add(user)
        db.session.commit()
        
        return success_response({
            'user': user.to_dict()
        }, '用户创建成功', 201)
        
    except Exception as e:
        return error_response(f'创建用户失败: {str(e)}', 'CREATE_USER_ERROR', 500)

@users_bp.route('/', methods=['GET'])
@login_required
def get_users():
    """
    获取用户列表
    """
    try:
        # 获取查询参数
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 100)  # 最多100条
        search = request.args.get('search', '').strip()
        role_filter = request.args.get('role', '').strip()
        is_active_filter = request.args.get('is_active', '').strip()
        
        # 构建查询
        query = User.query
        
        # 搜索过滤
        if search:
            query = query.filter(
                or_(
                    User.username.contains(search),
                    User.email.contains(search),
                    User.full_name.contains(search)
                )
            )
        
        # 角色过滤
        if role_filter:
            query = query.filter(User.role == role_filter)
        
        # 状态过滤
        if is_active_filter in ['true', 'false']:
            query = query.filter(User.is_active == (is_active_filter == 'true'))
        
        # 分页
        pagination = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        users = pagination.items
        
        return success_response({
            'users': [user.to_dict() for user in users],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        }, '获取用户列表成功')
        
    except Exception as e:
        return error_response(f'获取用户列表失败: {str(e)}', 'GET_USERS_ERROR', 500)

@users_bp.route('/<int:user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    """
    获取单个用户信息
    """
    try:
        user = User.query.get_or_404(user_id)
        
        # 检查权限：普通用户只能查看自己的信息，管理员可以查看所有
        if request.current_user['user_id'] != user_id and request.current_user.get('role') != 'admin':
            return error_response('没有权限查看该用户信息', 'ACCESS_DENIED', 403)
        
        return success_response({
            'user': user.to_dict(include_sensitive=False)
        }, '获取用户信息成功')
        
    except Exception as e:
        return error_response(f'获取用户信息失败: {str(e)}', 'GET_USER_ERROR', 404)

@users_bp.route('/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """
    更新用户信息
    """
    try:
        user = User.query.get_or_404(user_id)
        
        # 检查权限：普通用户只能修改自己的信息，管理员可以修改所有
        if request.current_user['user_id'] != user_id and request.current_user.get('role') != 'admin':
            return error_response('没有权限修改该用户信息', 'ACCESS_DENIED', 403)
        
        data = request.get_json()
        if not data:
            return error_response('没有提供更新数据', 'NO_DATA', 400)
        
        # 检查是否有敏感字段需要管理员权限
        sensitive_fields = ['role', 'is_active', 'is_verified']
        has_sensitive = any(field in data for field in sensitive_fields)
        
        if has_sensitive and request.current_user.get('role') != 'admin':
            return error_response('没有权限修改敏感字段', 'ADMIN_REQUIRED', 403)
        
        # 准备更新数据
        updateable_fields = [
            'full_name', 'phone', 'department', 'title', 'hospital'
        ]
        
        # 管理员可以更新敏感字段
        if request.current_user.get('role') == 'admin':
            updateable_fields.extend(['role', 'is_active', 'is_verified'])
        
        # 密码需要特殊处理
        if 'password' in data and data['password']:
            is_valid, error_msg = validate_password(data['password'])
            if not is_valid:
                return error_response(error_msg, 'INVALID_PASSWORD', 400)
            user.set_password(data['password'])
        
        # 更新其他字段
        for field in updateable_fields:
            if field in data:
                if field == 'email':
                    # 邮箱验证
                    if data[field]:
                        is_valid, error_msg = validate_email(data[field])
                        if not is_valid:
                            return error_response(error_msg, 'INVALID_EMAIL', 400)
                        # 检查邮箱是否被其他用户使用
                        existing_user = User.query.filter(
                            User.email == data[field],
                            User.id != user_id
                        ).first()
                        if existing_user:
                            return error_response('邮箱已被使用', 'EMAIL_EXISTS', 400)
                        user.email = data[field].lower()
                elif field == 'username':
                    # 用户名验证
                    if data[field]:
                        is_valid, error_msg = validate_username(data[field])
                        if not is_valid:
                            return error_response(error_msg, 'INVALID_USERNAME', 400)
                        # 检查用户名是否被其他用户使用
                        existing_user = User.query.filter(
                            User.username == data[field],
                            User.id != user_id
                        ).first()
                        if existing_user:
                            return error_response('用户名已存在', 'USERNAME_EXISTS', 400)
                        user.username = data[field]
                elif field == 'role':
                    # 角色验证
                    is_valid, error_msg = validate_role(data[field])
                    if not is_valid:
                        return error_response(error_msg, 'INVALID_ROLE', 400)
                    user.role = data[field]
                else:
                    setattr(user, field, data[field])
        
        # 保存更改
        from models.base import db
        db.session.commit()
        
        return success_response({
            'user': user.to_dict()
        }, '用户信息更新成功')
        
    except Exception as e:
        return error_response(f'更新用户信息失败: {str(e)}', 'UPDATE_USER_ERROR', 500)

@users_bp.route('/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """
    删除用户（软删除：设为非活跃状态）
    """
    try:
        user = User.query.get_or_404(user_id)
        
        # 不能删除管理员账户
        if user.role == 'admin':
            return error_response('不能删除管理员账户', 'CANNOT_DELETE_ADMIN', 400)
        
        # 软删除：设为非活跃状态
        user.is_active = False
        
        from models.base import db
        db.session.commit()
        
        return success_response(None, '用户已删除')
        
    except Exception as e:
        return error_response(f'删除用户失败: {str(e)}', 'DELETE_USER_ERROR', 500)

@users_bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    """
    获取当前用户个人信息
    """
    try:
        user = User.query.get(request.current_user['user_id'])
        
        if not user:
            return error_response('用户不存在', 'USER_NOT_FOUND', 404)
        
        return success_response({
            'user': user.to_dict(include_sensitive=False)
        }, '获取个人信息成功')
        
    except Exception as e:
        return error_response(f'获取个人信息失败: {str(e)}', 'GET_PROFILE_ERROR', 500)

@users_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """
    更新当前用户个人信息
    """
    try:
        user = User.query.get(request.current_user['user_id'])
        
        if not user:
            return error_response('用户不存在', 'USER_NOT_FOUND', 404)
        
        data = request.get_json()
        if not data:
            return error_response('没有提供更新数据', 'NO_DATA', 400)
        
        # 可以更新的字段
        updateable_fields = [
            'full_name', 'phone', 'department', 'title', 'hospital', 'password'
        ]
        
        # 密码需要特殊处理
        if 'password' in data and data['password']:
            is_valid, error_msg = validate_password(data['password'])
            if not is_valid:
                return error_response(error_msg, 'INVALID_PASSWORD', 400)
            user.set_password(data['password'])
        
        # 更新其他字段
        for field in ['full_name', 'phone', 'department', 'title', 'hospital']:
            if field in data:
                setattr(user, field, data[field])
        
        # 邮箱更新需要验证唯一性
        if 'email' in data and data['email']:
            email = data['email'].lower().strip()
            is_valid, error_msg = validate_email(email)
            if not is_valid:
                return error_response(error_msg, 'INVALID_EMAIL', 400)
            
            existing_user = User.query.filter(
                User.email == email,
                User.id != user.id
            ).first()
            if existing_user:
                return error_response('邮箱已被使用', 'EMAIL_EXISTS', 400)
            user.email = email
        
        # 用户名更新需要验证唯一性
        if 'username' in data and data['username']:
            username = data['username'].strip()
            is_valid, error_msg = validate_username(username)
            if not is_valid:
                return error_response(error_msg, 'INVALID_USERNAME', 400)
            
            existing_user = User.query.filter(
                User.username == username,
                User.id != user.id
            ).first()
            if existing_user:
                return error_response('用户名已存在', 'USERNAME_EXISTS', 400)
            user.username = username
        
        # 保存更改
        from models.base import db
        db.session.commit()
        
        return success_response({
            'user': user.to_dict()
        }, '个人信息更新成功')
        
    except Exception as e:
        return error_response(f'更新个人信息失败: {str(e)}', 'UPDATE_PROFILE_ERROR', 500)

@users_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """
    修改密码
    """
    try:
        user = User.query.get(request.current_user['user_id'])
        
        if not user:
            return error_response('用户不存在', 'USER_NOT_FOUND', 404)
        
        data = request.get_json()
        
        # 验证必填字段
        is_valid, missing_fields = validate_required_fields(data, [
            'current_password', 'new_password'
        ])
        
        if not is_valid:
            return error_response(
                f"缺少必填字段: {', '.join(missing_fields)}",
                'MISSING_REQUIRED_FIELDS',
                400
            )
        
        current_password = data['current_password']
        new_password = data['new_password']
        
        # 验证当前密码
        if not user.check_password(current_password):
            return error_response('当前密码错误', 'INVALID_CURRENT_PASSWORD', 400)
        
        # 验证新密码
        is_valid, error_msg = validate_password(new_password)
        if not is_valid:
            return error_response(error_msg, 'INVALID_NEW_PASSWORD', 400)
        
        # 更新密码
        user.set_password(new_password)
        
        from models.base import db
        db.session.commit()
        
        return success_response(None, '密码修改成功')
        
    except Exception as e:
        return error_response(f'修改密码失败: {str(e)}', 'CHANGE_PASSWORD_ERROR', 500)

@users_bp.route('/export', methods=['GET'])
@login_required
def export_users():
    """
    导出用户列表为Excel文件
    """
    try:
        # 获取查询参数
        search = request.args.get('search', '').strip()
        role_filter = request.args.get('role', '').strip()
        is_active_filter = request.args.get('is_active', '').strip()
        
        # 构建查询
        query = User.query
        
        # 搜索过滤
        if search:
            query = query.filter(
                or_(
                    User.username.contains(search),
                    User.email.contains(search),
                    User.full_name.contains(search)
                )
            )
        
        # 角色过滤
        if role_filter:
            query = query.filter(User.role == role_filter)
        
        # 状态过滤
        if is_active_filter in ['true', 'false']:
            query = query.filter(User.is_active == (is_active_filter == 'true'))
        
        # 获取所有匹配的用户
        users = query.order_by(User.created_at.desc()).all()
        
        # 准备数据
        data = []
        for user in users:
            data.append({
                'ID': user.id,
                '用户名': user.username,
                '姓名': user.full_name,
                '邮箱': user.email,
                '角色': '管理员' if user.role == 'admin' else '医生',
                '状态': '活跃' if user.is_active else '非活跃',
                '已验证': '是' if user.is_verified else '否',
                '部门': user.department or '',
                '职称': user.title or '',
                '医院': user.hospital or '',
                '电话': user.phone or '',
                '创建时间': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else '',
                '最后登录': user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else '从未登录'
            })
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 创建Excel文件
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='用户列表', index=False)
            
            # 获取工作表对象
            worksheet = writer.sheets['用户列表']
            
            # 调整列宽
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 30)  # 最大宽度为30
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        # 生成文件名
        filename = f"用户列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # 返回文件
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return error_response(f'导出用户列表失败: {str(e)}', 'EXPORT_USERS_ERROR', 500)