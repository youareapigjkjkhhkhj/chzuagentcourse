# API路由初始化
from flask import Blueprint

api_bp = Blueprint('api', __name__)

from app.api import auth, documents, qa, users, categories, tags, stats

# 注册路由模块
auth.register_routes(api_bp)
documents.register_routes(api_bp)
qa.register_routes(api_bp)
users.register_routes(api_bp)
categories.register_routes(api_bp)
tags.register_routes(api_bp)
stats.register_routes(api_bp)