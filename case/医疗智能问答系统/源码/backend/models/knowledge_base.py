#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库模型
"""

from datetime import datetime
from .base import db
import json


class KnowledgeBase(db.Model):
    """知识库模型"""
    __tablename__ = 'knowledge_bases'
    
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    embedding_model = db.Column(db.String(100))  # 该知识库使用的嵌入模型
    status = db.Column(db.String(20), default='active', nullable=False)  # active, archived
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 关系（向量数据存储在独立的 PostgreSQL 数据库中）
    documents = db.relationship('Document', backref='knowledge_base', cascade='all, delete-orphan', lazy='dynamic')
    
    def __repr__(self):
        return f'<KnowledgeBase {self.name}>'
    
    def to_dict(self, include_stats=False):
        """转换为字典格式"""
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'embeddingModel': self.embedding_model,
            'status': self.status,
            'createdBy': self.created_by,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_stats:
            from .document import Document
            result['totalDocuments'] = self.documents.count()
            result['publishedDocuments'] = self.documents.filter_by(status='published').count()
            result['totalVectors'] = db.session.query(db.func.sum(Document.chunk_count)).filter(
                Document.kb_id == self.id
            ).scalar() or 0
        
        return result
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建实例"""
        return cls(
            id=data.get('id'),
            name=data.get('name'),
            description=data.get('description'),
            embedding_model=data.get('embeddingModel'),
            status=data.get('status', 'active'),
            created_by=data.get('createdBy')
        )
