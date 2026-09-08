# 启动文件
import os
from app import create_app, db

app = create_app(os.getenv('FLASK_ENV', 'development'))

if __name__ == '__main__':
    with app.app_context():
        # 创建数据库表
        db.create_all()
        
        # 创建默认管理员用户
        from app.models.user import User
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                real_name='系统管理员',
                department='技术部',
                role='admin'
            )
            admin.set_password('admin123456')
            db.session.add(admin)
            db.session.commit()
            print("Default admin user created: admin/admin123456")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )