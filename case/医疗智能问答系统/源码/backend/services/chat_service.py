#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天记录服务层
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import desc, and_

from models import db, ChatSession, ChatMessage, User, ModelConfig, KnowledgeBase


class ChatService:
    """聊天记录服务类"""
    
    @staticmethod
    def create_session(user_id: int, title: str, model_id: Optional[int] = None, 
                      knowledge_base_id: Optional[str] = None) -> ChatSession:
        """创建新的聊天会话"""
        session_id = str(uuid.uuid4())
        session = ChatSession(
            id=session_id,
            user_id=user_id,
            title=title,
            model_id=model_id,
            knowledge_base_id=knowledge_base_id
        )
        db.session.add(session)
        db.session.commit()
        return session
    
    @staticmethod
    def get_session_by_id(session_id: str, user_id: Optional[int] = None) -> Optional[ChatSession]:
        """根据ID获取聊天会话"""
        query = ChatSession.query.filter_by(id=session_id)
        if user_id:
            query = query.filter_by(user_id=user_id)
        return query.first()
    
    @staticmethod
    def get_user_sessions(user_id: int, limit: int = 20, offset: int = 0) -> List[ChatSession]:
        """获取用户的聊天会话列表"""
        return ChatSession.query.filter_by(user_id=user_id).order_by(
            desc(ChatSession.updated_at)
        ).offset(offset).limit(limit).all()
    
    @staticmethod
    def update_session_title(session_id: str, title: str, user_id: Optional[int] = None) -> bool:
        """更新会话标题"""
        session = ChatService.get_session_by_id(session_id, user_id)
        if not session:
            return False
        
        session.title = title
        session.updated_at = datetime.utcnow()
        db.session.commit()
        return True
    
    @staticmethod
    def delete_session(session_id: str, user_id: Optional[int] = None) -> bool:
        """删除聊天会话及其所有消息"""
        session = ChatService.get_session_by_id(session_id, user_id)
        if not session:
            return False
        
        db.session.delete(session)
        db.session.commit()
        return True
    
    @staticmethod
    def add_message(session_id: str, content: str, message_type: str = 'user', 
                   role: str = 'user', tokens: int = 0, model_response_time: float = 0,
                   from_knowledge_base: bool = False, sources: Optional[List[Dict[str, Any]]] = None) -> ChatMessage:
        """添加聊天消息"""
        message_id = str(uuid.uuid4())
        message = ChatMessage(
            id=message_id,
            session_id=session_id,
            content=content,
            message_type=message_type,
            role=role,
            tokens=tokens,
            model_response_time=model_response_time,
            from_knowledge_base=from_knowledge_base,
            sources=sources
        )
        db.session.add(message)
        
        # 更新会话的最后更新时间
        session = ChatSession.query.filter_by(id=session_id).first()
        if session:
            session.updated_at = datetime.utcnow()
        
        db.session.commit()
        return message
    
    @staticmethod
    def get_session_messages(session_id: str, user_id: Optional[int] = None) -> List[ChatMessage]:
        """获取会话的所有消息"""
        # 验证会话是否存在且属于该用户
        if user_id:
            session = ChatService.get_session_by_id(session_id, user_id)
            if not session:
                return []
        
        return ChatMessage.query.filter_by(session_id=session_id).order_by(
            ChatMessage.timestamp
        ).all()
    
    @staticmethod
    def get_message_by_id(message_id: str, user_id: Optional[int] = None) -> Optional[ChatMessage]:
        """根据ID获取消息"""
        message = ChatMessage.query.filter_by(id=message_id).first()
        if not message:
            return None
        
        # 如果指定了用户ID，验证消息所属会话是否属于该用户
        if user_id:
            session = ChatService.get_session_by_id(message.session_id, user_id)
            if not session:
                return None
        
        return message
    
    @staticmethod
    def delete_message(message_id: str, user_id: Optional[int] = None) -> bool:
        """删除消息"""
        message = ChatService.get_message_by_id(message_id, user_id)
        if not message:
            return False
        
        db.session.delete(message)
        db.session.commit()
        return True
    
    @staticmethod
    def get_user_chat_statistics(user_id: int) -> Dict[str, Any]:
        """获取用户聊天统计信息"""
        # 总会话数
        total_sessions = ChatSession.query.filter_by(user_id=user_id).count()
        
        # 总消息数
        total_messages = db.session.query(ChatMessage).join(ChatSession).filter(
            ChatSession.user_id == user_id
        ).count()
        
        # 总token数
        total_tokens = db.session.query(db.func.sum(ChatMessage.tokens)).join(ChatSession).filter(
            and_(ChatSession.user_id == user_id, ChatMessage.role == 'assistant')
        ).scalar() or 0
        
        # 平均响应时间
        avg_response_time = db.session.query(db.func.avg(ChatMessage.model_response_time)).join(ChatSession).filter(
            and_(ChatSession.user_id == user_id, ChatMessage.role == 'assistant')
        ).scalar() or 0
        
        # 知识库使用率
        kb_messages = db.session.query(ChatMessage).join(ChatSession).filter(
            and_(
                ChatSession.user_id == user_id,
                ChatMessage.role == 'assistant',
                ChatMessage.from_knowledge_base == True
            )
        ).count()
        
        ai_messages = db.session.query(ChatMessage).join(ChatSession).filter(
            and_(
                ChatSession.user_id == user_id,
                ChatMessage.role == 'assistant'
            )
        ).count()
        
        kb_usage_rate = (kb_messages / ai_messages * 100) if ai_messages > 0 else 0
        
        return {
            'totalSessions': total_sessions,
            'totalMessages': total_messages,
            'totalTokens': int(total_tokens),
            'avgResponseTime': round(avg_response_time, 2),
            'kbUsageRate': round(kb_usage_rate, 2)
        }
    
    @staticmethod
    def export_session_messages(session_id: str, user_id: Optional[int] = None, 
                               format: str = 'json') -> Optional[Dict[str, Any]]:
        """导出会话消息"""
        session = ChatService.get_session_by_id(session_id, user_id)
        if not session:
            return None
        
        messages = ChatService.get_session_messages(session_id)
        
        export_data = {
            'session': session.to_dict(),
            'messages': [msg.to_dict() for msg in messages]
        }
        
        return export_data