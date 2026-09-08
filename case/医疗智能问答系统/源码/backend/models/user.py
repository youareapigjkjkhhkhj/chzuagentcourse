#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户模型
"""

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .base import db

class User(db.Model):
    """用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), default='user', nullable=False)  # user, admin, doctor
    department = db.Column(db.String(100), nullable=True)  # 科室
    title = db.Column(db.String(100), nullable=True)  # 职称
    hospital = db.Column(db.String(200), nullable=True)  # 医院
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        """设置密码"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self, include_sensitive=False):
        """转换为字典"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'name': self.full_name,  # 前端使用name字段
            'fullName': self.full_name,  # 兼容字段
            'phone': self.phone,
            'role': self.role,
            'department': self.department,
            'title': self.title,
            'hospital': self.hospital,
            'isActive': self.is_active,  # 前端使用camelCase
            'isVerified': self.is_verified,  # 前端使用camelCase
            'createdAt': self.created_at.isoformat() if self.created_at else None,  # 前端使用camelCase
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,  # 前端使用camelCase
            'lastLogin': self.last_login.isoformat() if self.last_login else None  # 前端使用camelCase
        }
        if include_sensitive:
            data['password_hash'] = self.password_hash
        return data