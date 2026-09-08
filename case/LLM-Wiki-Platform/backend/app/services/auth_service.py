# 认证服务
from datetime import datetime
from app import db
from app.models.user import User

class AuthService:
    """认证服务"""
    
    @staticmethod
    def login(username, password):
        """用户登录"""
        user = User.query.filter_by(username=username).first()
        
        if not user:
            return None, 'Invalid username or password'
        
        if not user.check_password(password):
            return None, 'Invalid username or password'
        
        if user.status != 'active':
            return None, 'Account is disabled'
        
        # 更新登录信息
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        
        return user, None
    
    @staticmethod
    def register(data):
        """用户注册"""
        # 检查用户名是否已存在
        if User.query.filter_by(username=data['username']).first():
            return None, 'Username already exists'
        
        # 检查邮箱是否已存在
        if User.query.filter_by(email=data['email']).first():
            return None, 'Email already exists'
        
        # 创建用户
        user = User(
            username=data['username'],
            email=data['email'],
            real_name=data.get('real_name'),
            department=data.get('department'),
            position=data.get('position'),
            role='viewer'
        )
        user.set_password(data['password'])
        
        db.session.add(user)
        db.session.commit()
        
        return user, None
    
    @staticmethod
    def get_user_by_id(user_id):
        """根据ID获取用户"""
        return User.query.get(user_id)
    
    @staticmethod
    def get_users(page=1, per_page=20):
        """获取用户列表"""
        query = User.query.filter_by(deleted_at=None)
        
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return {
            'items': [user.to_dict() for user in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        }
    
    @staticmethod
    def update_user(user_id, data):
        """更新用户信息"""
        try:
            user = User.query.get(user_id)
            if not user:
                return None, 'User not found'
            
            # 更新字段
            if 'real_name' in data:
                user.real_name = data['real_name']
            if 'department' in data:
                user.department = data['department']
            if 'position' in data:
                user.position = data['position']
            if 'phone' in data:
                user.phone = data['phone']
            if 'avatar' in data:
                user.avatar = data['avatar']
            if 'role' in data:
                user.role = data['role']
            if 'status' in data:
                user.status = data['status']
            
            # 更新密码
            if 'password' in data:
                user.set_password(data['password'])
            
            db.session.commit()
            
            return user, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def delete_user(user_id):
        """删除用户（软删除）"""
        try:
            user = User.query.get(user_id)
            if not user:
                return False, 'User not found'
            
            user.deleted_at = datetime.utcnow()
            user.status = 'inactive'
            
            db.session.commit()
            
            return True, None
        except Exception as e:
            db.session.rollback()
            return False, str(e)