#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库设置模型
"""

from .base import db
from datetime import datetime
import json

class KnowledgeBaseSettings(db.Model):
    """知识库设置模型"""
    __tablename__ = 'knowledge_base_settings'
    
    # 主键
    id = db.Column(db.String(50), primary_key=True, default='default')
    
    # 向量数据库设置
    vector_db_type = db.Column(db.String(50), default='pgvector', comment='向量数据库类型')
    connection_string = db.Column(db.String(500), comment='数据库连接字符串')
    
    # 嵌入模型设置
    embedding_model = db.Column(db.String(100), default='text-embedding-3-small', comment='嵌入模型')
    embedding_api_url = db.Column(db.String(500), comment='嵌入模型 API 地址')
    embedding_dimension = db.Column(db.Integer, default=1536, comment='向量维度')
    
    # 文本处理设置
    chunk_size = db.Column(db.Integer, default=1000, comment='文本块大小')
    chunk_overlap = db.Column(db.Integer, default=200, comment='文本块重叠')
    
    # 搜索设置
    similarity_threshold = db.Column(db.Float, default=0.7, comment='相似度阈值')
    max_search_results = db.Column(db.Integer, default=10, comment='最大搜索结果数')
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'vectorDbType': self.vector_db_type,
            'connectionString': self.connection_string,
            'embeddingModel': self.embedding_model,
            'embeddingApiUrl': self.embedding_api_url,
            'embeddingDimension': self.embedding_dimension,
            'chunkSize': self.chunk_size,
            'chunkOverlap': self.chunk_overlap,
            'similarityThreshold': self.similarity_threshold,
            'maxSearchResults': self.max_search_results,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建实例"""
        settings = cls()
        
        if 'vectorDbType' in data:
            settings.vector_db_type = data['vectorDbType']
        if 'connectionString' in data:
            settings.connection_string = data['connectionString']
        if 'embeddingModel' in data:
            settings.embedding_model = data['embeddingModel']
        if 'embeddingApiUrl' in data:
            settings.embedding_api_url = data['embeddingApiUrl']
        if 'embeddingDimension' in data:
            settings.embedding_dimension = data['embeddingDimension']
        if 'chunkSize' in data:
            settings.chunk_size = data['chunkSize']
        if 'chunkOverlap' in data:
            settings.chunk_overlap = data['chunkOverlap']
        if 'similarityThreshold' in data:
            settings.similarity_threshold = data['similarityThreshold']
        if 'maxSearchResults' in data:
            settings.max_search_results = data['maxSearchResults']
            
        return settings
    
    @classmethod
    def get_settings(cls):
        """获取知识库设置"""
        settings = cls.query.filter_by(id='default').first()
        if not settings:
            # 如果没有设置，创建默认设置
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings