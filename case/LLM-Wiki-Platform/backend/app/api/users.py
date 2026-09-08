# 用户API
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.auth_service import AuthService
from app.utils.decorators import require_permission

def register_routes(bp):
    """注册用户路由"""
    
    @bp.route('/users', methods=['GET'])
    @jwt_required()
    @require_permission('admin')
    def get_users():
        """获取用户列表"""
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        result = AuthService.get_users(page, per_page)
        
        return jsonify(result)
    
    @bp.route('/users/<int:user_id>', methods=['GET'])
    @jwt_required()
    @require_permission('admin')
    def get_user(user_id):
        """获取用户详情"""
        user = AuthService.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'user': user.to_dict()})
    
    @bp.route('/users/<int:user_id>', methods=['PUT'])
    @jwt_required()
    @require_permission('admin')
    def update_user(user_id):
        """更新用户信息"""
        data = request.get_json()
        
        user, error = AuthService.update_user(user_id, data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'user': user.to_dict()})
    
    @bp.route('/users/<int:user_id>', methods=['DELETE'])
    @jwt_required()
    @require_permission('admin')
    def delete_user(user_id):
        """删除用户"""
        success, error = AuthService.delete_user(user_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': 'User deleted successfully'})
    
    @bp.route('/users/profile', methods=['GET'])
    @jwt_required()
    def get_profile():
        """获取当前用户资料"""
        user_id = get_jwt_identity()
        user = AuthService.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'user': user.to_dict()})
    
    @bp.route('/users/profile', methods=['PUT'])
    @jwt_required()
    def update_profile():
        """更新当前用户资料"""
        user_id = get_jwt_identity()
        data = request.get_json()
        
        user, error = AuthService.update_user(user_id, data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'user': user.to_dict()})