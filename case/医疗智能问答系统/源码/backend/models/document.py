#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档模型
"""

from datetime import datetime
from .base import db
import json


class Document(db.Model):
    """文档模型"""
    __tablename__ = 'documents'
    
    id = db.Column(db.String(50), primary_key=True)
    kb_id = db.Column(db.String(50), db.ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), index=True)
    tags = db.Column(db.Text)  # JSON 格式
    author = db.Column(db.String(100))
    views = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)  # draft, processing, published, failed
    
    # 文件相关
    file_name = db.Column(db.String(255))
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)
    
    # 向量相关（向量实际存储在 PostgreSQL 中）
    chunk_count = db.Column(db.Integer, default=0, nullable=False)
    vector_status = db.Column(db.String(20), default='pending', nullable=False, index=True)  # pending, processing, completed, failed
    vector_error = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<Document {self.title}>'
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'kbId': self.kb_id,
            'title': self.title,
            'content': self.content,
            'category': self.category,
            'tags': json.loads(self.tags) if self.tags else [],
            'author': self.author,
            'views': self.views,
            'status': self.status,
            'fileName': self.file_name,
            'fileType': self.file_type,
            'fileSize': self.file_size,
            'chunkCount': self.chunk_count,
            'vectorStatus': self.vector_status,
            'vectorError': self.vector_error,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建实例"""
        tags = data.get('tags', [])
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)
        
        return cls(
            id=data.get('id'),
            kb_id=data.get('kbId'),
            title=data.get('title'),
            content=data.get('content'),
            category=data.get('category'),
            tags=tags,
            author=data.get('author'),
            views=data.get('views', 0),
            status=data.get('status', 'draft'),
            file_name=data.get('fileName'),
            file_type=data.get('fileType'),
            file_size=data.get('fileSize'),
            chunk_count=data.get('chunkCount', 0),
            vector_status=data.get('vectorStatus', 'pending'),
            vector_error=data.get('vectorError')
        )
