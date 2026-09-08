#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask应用工厂
"""

import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def create_app():
    """应用工厂函数"""
    app = Flask(__name__)
    
    # 配置
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///blindness.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # 配置CORS
    CORS(app, resources={
        r"/api/*": {
            "origins": ["http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.43.1:3000", "http://192.168.1.4:3000", "http://192.168.52.1:3000", "http://2.0.1.9:3000"],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # 初始化Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    # 对于API请求，返回401而不是重定向
    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            return jsonify({
                'success': False,
                'message': '需要认证',
                'error_code': 'UNAUTHORIZED'
            }), 401
        return login_manager.unauthorized()
    
    # 用户加载回调函数
    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return User.query.get(int(user_id))
    
    # 导入db实例并初始化
    from models.base import db
    db.init_app(app)
    
    # 注册蓝图
    from routes.auth import auth_bp
    from routes.users import users_bp
    from routes.models import models_bp
    from routes.kb import kb_bp
    from routes.settings import settings_bp
    from routes.chat import chat_bp
    from routes.chat_history import chat_bp as chat_history_bp
    from routes.image_analysis import analysis_bp
    from routes.reports import reports_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(models_bp, url_prefix='/api/models')
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(chat_history_bp)
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
    app.register_blueprint(kb_bp, url_prefix='/api/kb')
    app.register_blueprint(analysis_bp, url_prefix='/api/analysis')
    app.register_blueprint(reports_bp, url_prefix='/api/reports')
    
    @app.route('/uploads/images/<path:filename>')
    def serve_uploaded_image(filename):
        project_root = os.path.dirname(app.root_path)
        upload_folder = os.path.join(project_root, 'uploads', 'images')
        return send_from_directory(upload_folder, filename)
    
    # 创建数据库表
    with app.app_context():
        from models import (User, ModelConfig, KnowledgeBaseSettings, KnowledgeBase, Document, 
                          DocumentVector, ChatSession, ChatMessage, ImageAnalysis, AnalysisResult, 
                          ModelPrediction, DiagnosisReport)
        db.create_all()
        
        # 初始化向量数据库
        from models.document_vector import init_vector_db
        init_vector_db()
    
    return app
