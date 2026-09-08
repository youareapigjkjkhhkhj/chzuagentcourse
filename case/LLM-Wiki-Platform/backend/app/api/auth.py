# 认证API
from flask import request, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity
from app.services.auth_service import AuthService

def register_routes(bp):
    """注册认证路由"""
    
    @bp.route('/auth/login', methods=['POST'])
    def login():
        """用户登录"""
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        user, error = AuthService.login(username, password)
        if error:
            return jsonify({'error': error}), 401
        
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        return jsonify({
            'user': user.to_dict(),
            'access_token': access_token,
            'refresh_token': refresh_token
        })
    
    @bp.route('/auth/register', methods=['POST'])
    def register():
        """用户注册"""
        data = request.get_json()
        
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        user, error = AuthService.register(data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'user': user.to_dict()}), 201
    
    @bp.route('/auth/refresh', methods=['POST'])
    @jwt_required(refresh=True)
    def refresh():
        """刷新令牌"""
        current_user_id = get_jwt_identity()
        access_token = create_access_token(identity=current_user_id)
        return jsonify({'access_token': access_token})
    
    @bp.route('/auth/me', methods=['GET'])
    @jwt_required()
    def get_current_user():
        """获取当前用户信息"""
        current_user_id = get_jwt_identity()
        user = AuthService.get_user_by_id(current_user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({'user': user.to_dict()})