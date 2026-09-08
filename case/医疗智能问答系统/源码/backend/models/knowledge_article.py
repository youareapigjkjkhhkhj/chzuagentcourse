#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库文章数据模型
"""

from datetime import datetime
from .base import db
import json

class KnowledgeArticle(db.Model):
    """知识库文章模型"""
    __tablename__ = 'knowledge_articles'
    
    id = db.Column(db.String(50), primary_key=True)  # 字符串类型ID，与前端ID保持一致
    title = db.Column(db.String(200), nullable=False)  # 文章标题
    content = db.Column(db.Text, nullable=False)  # 文章内容
    category = db.Column(db.String(50), nullable=False)  # 分类
    tags = db.Column(db.Text, nullable=True)  # 标签，JSON格式存储
    author = db.Column(db.String(100), nullable=False)  # 作者
    views = db.Column(db.Integer, default=0, nullable=False)  # 浏览量
    status = db.Column(db.String(20), default='draft', nullable=False)  # 状态：draft、published
    
    # 向量数据库相关字段 (legacy - kept for backward compatibility)
    vector_id = db.Column(db.String(100), nullable=True)  # Legacy vector ID (no longer used with pgvector)
    chunk_count = db.Column(db.Integer, default=0, nullable=False)  # 分块数量
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<KnowledgeArticle {self.title}>'
    
    def to_dict(self):
        """转换为字典，匹配前端KnowledgeArticle接口"""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'category': self.category,
            'tags': json.loads(self.tags) if self.tags else [],
            'createdAt': self.created_at.strftime('%Y-%m-%d'),
            'updatedAt': self.updated_at.strftime('%Y-%m-%d'),
            'author': self.author,
            'views': self.views,
            'status': self.status
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建对象"""
        tags = data.get('tags', [])
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)
        
        return cls(
            id=data.get('id'),
            title=data.get('title'),
            content=data.get('content'),
            category=data.get('category'),
            tags=tags,
            author=data.get('author'),
            views=data.get('views', 0),
            status=data.get('status', 'draft')
        )