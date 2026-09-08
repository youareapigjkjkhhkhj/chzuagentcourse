#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天记录API路由
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
import json

from services.chat_service import ChatService
from models import db, ChatSession, ChatMessage, User
from utils.auth import login_required, get_current_user

# 创建蓝图
chat_bp = Blueprint('chat_history', __name__, url_prefix='/api')


@chat_bp.route('/chat/sessions', methods=['GET'])
@login_required
def get_chat_sessions():
    """获取用户的聊天会话列表"""
    try:
        user_id = get_current_user()['user_id']
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        
        sessions = ChatService.get_user_sessions(user_id, limit, offset)
        return jsonify({
            'success': True,
            'data': [session.to_dict() for session in sessions],
            'total': len(sessions)
        })
    except Exception as e:
        current_app.logger.error(f"获取聊天会话列表失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取聊天会话列表失败'}), 500


@chat_bp.route('/chat/sessions', methods=['POST'])
@login_required
def create_chat_session():
    """创建新的聊天会话"""
    try:
        user_id = get_current_user()['user_id']
        data = request.get_json()
        
        if not data or 'title' not in data:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        title = data['title']
        model_id = data.get('modelId')
        knowledge_base_id = data.get('knowledgeBaseId')
        
        session = ChatService.create_session(
            user_id=user_id,
            title=title,
            model_id=model_id,
            knowledge_base_id=knowledge_base_id
        )
        
        return jsonify({
            'success': True,
            'data': session.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"创建聊天会话失败: {str(e)}")
        return jsonify({'success': False, 'message': '创建聊天会话失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>', methods=['GET'])
@login_required
def get_chat_session(session_id):
    """获取指定聊天会话详情"""
    try:
        user_id = get_current_user()['user_id']
        session = ChatService.get_session_by_id(session_id, user_id)
        
        if not session:
            return jsonify({'success': False, 'message': '聊天会话不存在'}), 404
        
        return jsonify({
            'success': True,
            'data': session.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"获取聊天会话详情失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取聊天会话详情失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>', methods=['PUT'])
@login_required
def update_chat_session(session_id):
    """更新聊天会话信息"""
    try:
        user_id = get_current_user()['user_id']
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': '请求数据为空'}), 400
        
        # 目前只支持更新标题
        if 'title' in data:
            success = ChatService.update_session_title(session_id, data['title'], user_id)
            if not success:
                return jsonify({'success': False, 'message': '聊天会话不存在或无权限'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"更新聊天会话失败: {str(e)}")
        return jsonify({'success': False, 'message': '更新聊天会话失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>', methods=['DELETE'])
@login_required
def delete_chat_session(session_id):
    """删除聊天会话"""
    try:
        user_id = get_current_user()['user_id']
        success = ChatService.delete_session(session_id, user_id)
        
        if not success:
            return jsonify({'success': False, 'message': '聊天会话不存在或无权限'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"删除聊天会话失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除聊天会话失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>/messages', methods=['GET'])
@login_required
def get_chat_messages(session_id):
    """获取会话的所有消息"""
    try:
        user_id = get_current_user()['user_id']
        messages = ChatService.get_session_messages(session_id, user_id)
        
        return jsonify({
            'success': True,
            'data': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        current_app.logger.error(f"获取聊天消息失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取聊天消息失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>/messages', methods=['POST'])
@login_required
def add_chat_message(session_id):
    """添加聊天消息"""
    try:
        user_id = get_current_user()['user_id']
        data = request.get_json()
        
        if not data or 'content' not in data:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 验证会话是否存在且属于该用户
        session = ChatService.get_session_by_id(session_id, user_id)
        if not session:
            return jsonify({'success': False, 'message': '聊天会话不存在或无权限'}), 404
        
        content = data['content']
        message_type = data.get('messageType', 'user')
        role = data.get('role', 'user')
        tokens = data.get('tokens', 0)
        model_response_time = data.get('modelResponseTime', 0)
        from_knowledge_base = data.get('fromKnowledgeBase', False)
        sources = data.get('sources')
        
        message = ChatService.add_message(
            session_id=session_id,
            content=content,
            message_type=message_type,
            role=role,
            tokens=tokens,
            model_response_time=model_response_time,
            from_knowledge_base=from_knowledge_base,
            sources=sources
        )
        
        return jsonify({
            'success': True,
            'data': message.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"添加聊天消息失败: {str(e)}")
        return jsonify({'success': False, 'message': '添加聊天消息失败'}), 500


@chat_bp.route('/chat/messages/<message_id>', methods=['DELETE'])
@login_required
def delete_chat_message(message_id):
    """删除聊天消息"""
    try:
        user_id = get_current_user()['user_id']
        success = ChatService.delete_message(message_id, user_id)
        
        if not success:
            return jsonify({'success': False, 'message': '消息不存在或无权限'}), 404
        
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"删除聊天消息失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除聊天消息失败'}), 500


@chat_bp.route('/chat/statistics', methods=['GET'])
@login_required
def get_chat_statistics():
    """获取聊天统计数据"""
    try:
        user_id = get_current_user()['user_id']
        stats = ChatService.get_user_chat_statistics(user_id)
        
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        current_app.logger.error(f"获取聊天统计数据失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取聊天统计数据失败'}), 500


@chat_bp.route('/chat/sessions/<session_id>/export', methods=['GET'])
@login_required
def export_chat_session(session_id):
    """导出聊天会话"""
    try:
        user_id = get_current_user()['user_id']
        export_format = request.args.get('format', 'json')
        
        # 验证会话是否存在且属于该用户
        session = ChatService.get_session_by_id(session_id, user_id)
        if not session:
            return jsonify({'success': False, 'message': '聊天会话不存在或无权限'}), 404
        
        # 获取会话消息
        messages = ChatService.get_session_messages(session_id, user_id)
        
        if export_format == 'json':
            export_data = {
                'session': session.to_dict(),
                'messages': [msg.to_dict() for msg in messages],
                'export_time': datetime.now().isoformat()
            }
            return jsonify({
                'success': True,
                'data': export_data
            })
        elif export_format == 'txt':
            # 简单的文本格式导出
            lines = [
                f"会话标题: {session.title}",
                f"创建时间: {session.created_at}",
                f"更新时间: {session.updated_at}",
                "-" * 50
            ]
            
            for msg in messages:
                role = "用户" if msg.role == 'user' else "助手"
                lines.append(f"\n{role} ({msg.created_at}):")
                lines.append(msg.content)
            
            return '\n'.join(lines), 200, {
                'Content-Type': 'text/plain; charset=utf-8',
                'Content-Disposition': f'attachment; filename=chat_{session_id}.txt'
            }
        else:
            return jsonify({'success': False, 'message': '不支持的导出格式'}), 400
            
    except Exception as e:
        current_app.logger.error(f"导出聊天会话失败: {str(e)}")
        return jsonify({'success': False, 'message': '导出聊天会话失败'}), 500