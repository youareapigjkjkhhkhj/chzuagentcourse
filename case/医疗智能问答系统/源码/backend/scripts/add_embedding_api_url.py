#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
添加 embedding_api_url 字段到 knowledge_base_settings 表
适用于 SQLite 数据库
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models.base import db
from models.settings import KnowledgeBaseSettings
from models.model import ModelConfig
from sqlalchemy import text

def add_embedding_api_url_column():
    """添加 embedding_api_url 列"""
    app = create_app()
    
    with app.app_context():
        try:
            # 检查列是否已存在
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('knowledge_base_settings')]
            
            if 'embedding_api_url' in columns:
                print("✓ embedding_api_url 列已存在")
                return True
            
            print("添加 embedding_api_url 列...")
            
            # 添加列
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE knowledge_base_settings ADD COLUMN embedding_api_url VARCHAR(500)"
                ))
                conn.commit()
            
            print("✓ 成功添加 embedding_api_url 列")
            
            # 更新现有记录
            update_existing_records()
            
            return True
            
        except Exception as e:
            print(f"✗ 添加列失败: {e}")
            return False

def update_existing_records():
    """更新现有记录的 embedding_api_url"""
    try:
        print("\n更新现有设置记录...")
        
        # 获取所有设置记录
        settings_list = KnowledgeBaseSettings.query.all()
        
        if not settings_list:
            print("没有需要更新的设置记录")
            return
        
        updated_count = 0
        
        for settings in settings_list:
            # 如果已有 API URL，跳过
            if settings.embedding_api_url:
                continue
            
            # 如果没有嵌入模型，跳过
            if not settings.embedding_model:
                continue
            
            # 查找对应的模型配置
            model_config = ModelConfig.query.filter_by(
                model_name=settings.embedding_model,
                type='embedding'
            ).first()
            
            if model_config and model_config.api_endpoint:
                api_url = model_config.api_endpoint
                
                # 确保 URL 包含 /api/embeddings 路径
                if not api_url.endswith('/api/embeddings') and not api_url.endswith('/embeddings'):
                    api_url = f"{api_url}/api/embeddings"
                
                settings.embedding_api_url = api_url
                updated_count += 1
                
                print(f"  ✓ 更新设置 {settings.id}: {settings.embedding_model} -> {api_url}")
        
        if updated_count > 0:
            db.session.commit()
            print(f"\n✓ 成功更新 {updated_count} 条记录")
        else:
            print("\n没有需要更新的记录")
        
    except Exception as e:
        db.session.rollback()
        print(f"✗ 更新记录失败: {e}")

if __name__ == '__main__':
    print("=" * 60)
    print("添加 embedding_api_url 字段")
    print("=" * 60)
    
    success = add_embedding_api_url_column()
    
    if success:
        print("\n" + "=" * 60)
        print("✅ 迁移完成！")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ 迁移失败！")
        print("=" * 60)
        sys.exit(1)
