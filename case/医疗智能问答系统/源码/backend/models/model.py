#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型配置数据库模型
"""

from datetime import datetime
from .base import db

class ModelConfig(db.Model):
    """模型配置"""
    __tablename__ = 'models'
    
    id = db.Column(db.String(50), primary_key=True)  # 字符串类型ID，与前端ID保持一致
    name = db.Column(db.String(100), nullable=False)  # 模型名称
    provider = db.Column(db.String(50), nullable=False)  # 模型提供商：openai、ollama、qianwen
    type = db.Column(db.String(20), nullable=False)  # 模型类型：chat、embedding
    model_name = db.Column(db.String(100), nullable=False)  # 具体模型名称，如 gpt-4、llama2
    api_key = db.Column(db.String(255), nullable=True)  # API密钥，可能为空(Ollama不需要)
    api_endpoint = db.Column(db.String(255), nullable=True)  # API端点URL
    temperature = db.Column(db.Float, nullable=True)  # 温度参数
    max_tokens = db.Column(db.Integer, nullable=True)  # 最大令牌数
    top_p = db.Column(db.Float, nullable=True)  # TopP参数
    system_prompt = db.Column(db.Text, nullable=True)  # 系统提示
    status = db.Column(db.String(20), default='active', nullable=False)  # 状态：active、inactive、error、testing
    is_default = db.Column(db.Boolean, default=False, nullable=False)  # 是否为默认模型
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    description = db.Column(db.Text, nullable=True)  # 模型描述
    
    def __repr__(self):
        return f'<ModelConfig {self.name}>'
    
    def to_dict(self):
        """转换为字典，匹配前端ModelConfig接口"""
        return {
            'id': self.id,
            'name': self.name,
            'provider': self.provider,
            'type': self.type,
            'modelName': self.model_name,
            'apiKey': self.api_key,
            'apiEndpoint': self.api_endpoint,
            'temperature': self.temperature,
            'maxTokens': self.max_tokens,
            'topP': self.top_p,
            'systemPrompt': self.system_prompt,
            'status': self.status,
            'isDefault': self.is_default,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'description': self.description
        }