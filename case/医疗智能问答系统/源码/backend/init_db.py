#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本
"""

import os
import sys
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置环境变量为开发模式
os.environ['FLASK_ENV'] = 'development'

# 导入并运行应用
from app import create_app
from models.base import db
from models.model import ModelConfig

def init_db():
    """初始化数据库"""
    app = create_app()
    
    with app.app_context():
        # 创建所有表
        db.create_all()
        
        # 检查是否已有模型配置数据
        existing_models = ModelConfig.query.count()
        if existing_models == 0:
            print("未发现模型配置数据，正在添加默认模型...")
            
            # 添加默认模型配置
            default_models = [
                {
                    'id': 'default_openai_chat',
                    'name': 'GPT-4 医学助手',
                    'provider': 'OPENAI',
                    'type': 'chat',
                    'model_name': 'gpt-4',
                    'api_key': '',
                    'api_endpoint': 'https://api.openai.com/v1',
                    'temperature': 0.7,
                    'max_tokens': 2000,
                    'top_p': 1.0,
                    'status': 'inactive',
                    'is_default': True,
                    'description': 'GPT-4医学助手配置，专业的医疗问答模型'
                },
                {
                    'id': 'default_ollama_local',
                    'name': '本地 Llama2',
                    'provider': 'OLLAMA',
                    'type': 'chat',
                    'model_name': 'llama2:7b',
                    'api_key': '',
                    'api_endpoint': 'http://localhost:11434',
                    'temperature': 0.8,
                    'max_tokens': 1500,
                    'top_p': 0.9,
                    'status': 'inactive',
                    'is_default': False,
                    'description': '本地Ollama部署的Llama2 7B模型'
                },
                {
                    'id': 'default_qianwen_turbo',
                    'name': '千问 Turbo',
                    'provider': 'QIANWEN',
                    'type': 'chat',
                    'model_name': 'qwen-turbo',
                    'api_key': '',
                    'api_endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    'temperature': 0.7,
                    'max_tokens': 2000,
                    'top_p': 1.0,
                    'status': 'inactive',
                    'is_default': False,
                    'description': '千问Turbo模型，高效的中文对话模型'
                }
            ]
            
            for model_data in default_models:
                model = ModelConfig(**model_data)
                db.session.add(model)
            
            db.session.commit()
            print(f"已添加{len(default_models)}个默认模型配置")
        else:
            print(f"数据库中已有{existing_models}个模型配置")

if __name__ == '__main__':
    init_db()