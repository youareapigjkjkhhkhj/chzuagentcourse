#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型包
"""

from .base import db
from .user import User
from .model import ModelConfig
from .knowledge_article import KnowledgeArticle
from .settings import KnowledgeBaseSettings
from .knowledge_base import KnowledgeBase
from .document import Document
from .document_vector import DocumentVector
from .chat import ChatSession, ChatMessage
from .image_analysis import ImageAnalysis, AnalysisResult, ModelPrediction, DiagnosisReport

# 确保所有模型在应用初始化时被导入
__all__ = [
    'db', 
    'User', 
    'ModelConfig', 
    'KnowledgeArticle', 
    'KnowledgeBaseSettings',
    'KnowledgeBase',
    'Document',
    'DocumentVector',
    'ChatSession',
    'ChatMessage',
    'ImageAnalysis',
    'AnalysisResult',
    'ModelPrediction',
    'DiagnosisReport'
]