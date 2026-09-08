#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档向量模型 - 独立的 PostgreSQL + pgvector 数据库
"""

from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSON
from pgvector.sqlalchemy import Vector
import os

# 创建独立的向量数据库 Base
VectorBase = declarative_base()

# 向量数据库引擎（延迟初始化）
_vector_engine = None
_VectorSession = None


def init_vector_db(connection_string=None):
    """初始化向量数据库连接"""
    global _vector_engine, _VectorSession
    
    if connection_string is None:
        # 确保环境变量已加载
        from dotenv import load_dotenv
        load_dotenv()
        connection_string = os.getenv('VECTOR_DATABASE_URL', 'postgresql://localhost/vectordb')
    
    _vector_engine = create_engine(connection_string)
    _VectorSession = sessionmaker(bind=_vector_engine)
    
    # 创建表
    VectorBase.metadata.create_all(_vector_engine)
    
    return _vector_engine


def get_vector_session():
    """获取向量数据库会话"""
    if _VectorSession is None:
        init_vector_db()
    return _VectorSession()


class DocumentVector(VectorBase):
    """文档向量模型 - 存储在独立的 PostgreSQL + pgvector 数据库"""
    __tablename__ = 'document_vectors'
    
    id = Column(String(50), primary_key=True)
    document_id = Column(String(50), nullable=False, index=True)  # 引用 SQLite 中的 document.id
    kb_id = Column(String(50), nullable=False, index=True)  # 引用 SQLite 中的 knowledge_base.id
    
    # 文本块信息
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    
    # 向量数据 - 使用 pgvector 的 vector 类型
    # 维度根据嵌入模型调整，从环境变量获取，默认 1024 (bge-m3)
    embedding = Column(Vector(int(os.getenv('EMBEDDING_DIMENSION', '1024'))))
    
    # 元数据（使用 meta_data 避免与 SQLAlchemy 的 metadata 冲突）
    meta_data = Column(JSON)  # 存储额外信息
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 复合索引
    __table_args__ = (
        Index('idx_document_vectors_kb_doc', 'kb_id', 'document_id'),
        Index('idx_document_vectors_chunk', 'document_id', 'chunk_index'),
    )
    
    def __repr__(self):
        return f'<DocumentVector {self.id} chunk={self.chunk_index}>'
    
    def to_dict(self, include_embedding=False):
        """转换为字典格式"""
        result = {
            'id': self.id,
            'documentId': self.document_id,
            'kbId': self.kb_id,
            'chunkIndex': self.chunk_index,
            'chunkText': self.chunk_text,
            'metadata': self.meta_data,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }
        
        if include_embedding and self.embedding:
            result['embedding'] = self.embedding
        
        return result
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建实例"""
        return cls(
            id=data.get('id'),
            document_id=data.get('documentId'),
            kb_id=data.get('kbId'),
            chunk_index=data.get('chunkIndex'),
            chunk_text=data.get('chunkText'),
            embedding=data.get('embedding'),
            meta_data=data.get('metadata')
        )
