# 装饰器
from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from app.models.user import User

def require_permission(permission):
    """权限检查装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = User.query.get(current_user_id)
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            # 检查权限
            role_permissions = {
                'admin': ['admin', 'editor', 'viewer'],
                'editor': ['editor', 'viewer'],
                'viewer': ['viewer']
            }
            
            if permission not in role_permissions.get(user.role, []):
                return jsonify({'error': 'Permission denied'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator