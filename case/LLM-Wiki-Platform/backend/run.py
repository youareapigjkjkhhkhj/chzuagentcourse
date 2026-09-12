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
        
        # 创建默认分类
        from app.models.document import Category, Tag
        if Category.query.count() == 0:
            default_categories = [
                Category(name='运维文档', description='运维相关文档', level=1, sort_order=1),
                Category(name='开发文档', description='开发相关文档', level=1, sort_order=2),
                Category(name='产品文档', description='产品相关文档', level=1, sort_order=3),
                Category(name='规范制度', description='公司规范制度', level=1, sort_order=4),
            ]
            for cat in default_categories:
                db.session.add(cat)
            db.session.commit()
            print("Default categories created")
        
        # 创建默认标签
        if Tag.query.count() == 0:
            default_tags = [
                Tag(name='重要', description='重要文档', color='#E6A23C'),
                Tag(name='紧急', description='紧急文档', color='#F56C6C'),
                Tag(name='教程', description='教程类文档', color='#409EFF'),
                Tag(name='最佳实践', description='最佳实践文档', color='#67C23A'),
                Tag(name='故障处理', description='故障处理文档', color='#909399'),
            ]
            for tag in default_tags:
                db.session.add(tag)
            db.session.commit()
            print("Default tags created")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )