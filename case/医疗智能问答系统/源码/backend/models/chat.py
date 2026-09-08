#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天记录模型
"""

from datetime import datetime
from .base import db

class ChatSession(db.Model):
    """聊天会话模型"""
    __tablename__ = 'chat_sessions'
    
    id = db.Column(db.String(36), primary_key=True)  # 使用UUID作为主键
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    model_id = db.Column(db.String(50), db.ForeignKey('models.id'), nullable=True)  # 使用的模型
    knowledge_base_id = db.Column(db.String(36), db.ForeignKey('knowledge_bases.id'), nullable=True)  # 使用的知识库
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # 关联关系
    user = db.relationship('User', backref=db.backref('chat_sessions', lazy=True, cascade='all, delete-orphan'))
    model = db.relationship('ModelConfig', backref=db.backref('chat_sessions', lazy=True))
    knowledge_base = db.relationship('KnowledgeBase', backref=db.backref('chat_sessions', lazy=True))
    messages = db.relationship('ChatMessage', backref=db.backref('session', lazy=True), cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ChatSession {self.id}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'userId': self.user_id,
            'title': self.title,
            'modelId': self.model_id,
            'knowledgeBaseId': self.knowledge_base_id,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'isActive': self.is_active,
            'messageCount': len(self.messages) if self.messages else 0,
            'lastMessage': self.messages[-1].content if self.messages and self.messages[-1] else None
        }


class ChatMessage(db.Model):
    """聊天消息模型"""
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.String(36), primary_key=True)  # 使用UUID作为主键
    session_id = db.Column(db.String(36), db.ForeignKey('chat_sessions.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='user', nullable=False)  # user, ai, system
    role = db.Column(db.String(20), default='user', nullable=False)  # user, assistant, system
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    tokens = db.Column(db.Integer, default=0)  # 消息token数量
    model_response_time = db.Column(db.Float, default=0)  # AI响应时间(秒)
    from_knowledge_base = db.Column(db.Boolean, default=False)  # 是否来自知识库
    sources = db.Column(db.JSON, default=None)  # 知识库来源信息
    
    def __repr__(self):
        return f'<ChatMessage {self.id}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'sessionId': self.session_id,
            'content': self.content,
            'messageType': self.message_type,
            'role': self.role,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'tokens': self.tokens,
            'modelResponseTime': self.model_response_time,
            'fromKnowledgeBase': self.from_knowledge_base,
            'sources': self.sources
        }