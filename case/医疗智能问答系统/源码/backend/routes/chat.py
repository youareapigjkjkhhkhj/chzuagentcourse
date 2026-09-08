#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天API路由
"""

import os
import json
import logging
import time
from flask import Blueprint, request, jsonify, Response, stream_template
from models.base import db
from models.model import ModelConfig
from models.knowledge_base import KnowledgeBase
from models.settings import KnowledgeBaseSettings
from models.user import User
from services.chat_service import ChatService
from utils.vector_manager import VectorManager
from utils.auth import login_required
import requests
from typing import Dict, Any, List, Optional
import queue
import threading

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)

def generate_stream_response(response_data: Dict[str, Any]) -> str:
    """生成流式响应数据"""
    return f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"

# 获取对话模型列表
@chat_bp.route('/models', methods=['GET'])
@login_required
def get_chat_models():
    """获取可用的对话模型列表"""
    try:
        # 获取所有对话模型
        chat_models = ModelConfig.query.filter_by(type='chat', status='active').all()
        
        models = []
        for model in chat_models:
            models.append({
                'id': model.id,
                'name': model.name,
                'provider': model.provider,
                'modelName': model.model_name,
                'apiEndpoint': model.api_endpoint,
                'isDefault': model.is_default,
                'description': model.description
            })
        
        return jsonify({
            'success': True,
            'message': '获取对话模型成功',
            'data': {
                'models': models
            }
        }), 200
    except Exception as e:
        logger.error(f"获取对话模型失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取对话模型失败: {str(e)}'
        }), 500

# 获取知识库列表
@chat_bp.route('/knowledge-bases', methods=['GET'])
@login_required
def get_knowledge_bases():
    """获取可用的知识库列表"""
    try:
        # 获取所有活跃的知识库
        knowledge_bases = KnowledgeBase.query.filter_by(status='active').all()
        
        kbs = []
        for kb in knowledge_bases:
            kbs.append({
                'id': kb.id,
                'name': kb.name,
                'description': kb.description,
                'embeddingModel': kb.embedding_model
            })
        
        return jsonify({
            'success': True,
            'message': '获取知识库成功',
            'data': {
                'knowledgeBases': kbs
            }
        }), 200
    except Exception as e:
        logger.error(f"获取知识库失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'获取知识库失败: {str(e)}'
        }), 500

# 聊天接口
@chat_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """发送聊天消息"""
    try:
        data = request.get_json()
        
        # 验证请求参数
        if not data or 'message' not in data:
            return jsonify({
                'success': False,
                'message': '缺少消息内容'
            }), 400
        
        message = data.get('message', '').strip()
        model_id = data.get('modelId')
        knowledge_base_id = data.get('knowledgeBaseId')
        use_knowledge_base = data.get('useKnowledgeBase', False)
        session_id = data.get('sessionId')  # 获取会话ID
        
        if not message:
            return jsonify({
                'success': False,
                'message': '消息内容不能为空'
            }), 400
        
        # 获取当前用户
        user_id = None
        if hasattr(request, 'current_user'):
            user_id = request.current_user.get('user_id')
        elif hasattr(request, 'user'):
            user_id = request.user.id
        else:
            # 如果没有用户信息，尝试从JWT中获取
            from flask_jwt_extended import get_jwt_identity
            user_id = get_jwt_identity()
        
        # 如果没有会话ID，创建新会话
        if not session_id:
            # 生成会话标题（使用消息的前20个字符）
            title = message[:20] + "..." if len(message) > 20 else message
            session = ChatService.create_session(
                user_id=user_id,
                title=title,
                model_id=model_id,
                knowledge_base_id=knowledge_base_id if use_knowledge_base else None
            )
            session_id = session.id
        else:
            # 验证会话是否存在
            session = ChatService.get_session_by_id(session_id, user_id)
            if not session:
                return jsonify({
                    'success': False,
                    'message': '聊天会话不存在或无权限'
                }), 404
        
        # 保存用户消息
        ChatService.add_message(
            session_id=session_id,
            content=message,
            message_type='user',
            role='user'
        )
        
        # 记录开始时间，用于计算响应时间
        start_time = time.time()
        
        # 获取对话模型
        model = None
        if model_id:
            model = ModelConfig.query.filter_by(id=model_id, type='chat', status='active').first()
        else:
            # 如果没有指定模型，使用默认对话模型
            model = ModelConfig.query.filter_by(type='chat', is_default=True, status='active').first()
        
        if not model:
            return jsonify({
                'success': False,
                'message': '未找到可用的对话模型'
            }), 400
        
        # 初始化向量管理器
        vector_manager = VectorManager()
        
        # 知识库检索
        context = ""
        sources = []
        if use_knowledge_base and knowledge_base_id:
            # 获取知识库信息
            kb = KnowledgeBase.query.filter_by(id=knowledge_base_id).first()
            if kb:
                # 更新向量管理器的嵌入模型
                vector_manager.embedding_model = kb.embedding_model
                
                # 获取知识库设置
                settings = KnowledgeBaseSettings.get_settings()
                
                # 检索知识库
                search_results = vector_manager.hybrid_search(
                    query=message,
                    kb_id=knowledge_base_id,
                    limit=5,
                    similarity_threshold=settings.similarity_threshold
                )
                
                if search_results:
                    # 构建上下文
                    context_parts = []
                    for result in search_results:
                        content = result.get('content', '')
                        title = result.get('title', '未知文档')
                        similarity = result.get('similarity', 0)
                        
                        context_parts.append(f"文档: {title}\n内容: {content}\n相似度: {similarity:.2f}\n")
                        sources.append({
                            'id': result.get('document_id', ''),
                            'title': title,
                            'content': content,
                            'similarity': similarity
                        })
                    
                    context = "\n".join(context_parts)
        
        # 构建系统提示
        system_prompt = model.system_prompt or "你是一个专业的医学助手，请根据提供的上下文回答用户的问题。如果上下文中没有相关信息，请基于你的专业知识回答。"
        
        if context:
            system_prompt = f"{system_prompt}\n\n请基于以下上下文信息回答用户的问题：\n\n{context}"
        
        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
        
        # 调用对话模型
        response = call_chat_model(model, messages)
        
        if not response:
            return jsonify({
                'success': False,
                'message': '调用对话模型失败'
            }), 500
        
        # 计算响应时间
        response_time = time.time() - start_time
        
        # 保存AI回复
        ChatService.add_message(
            session_id=session_id,
            content=response,
            message_type='ai',
            role='assistant',
            model_response_time=response_time,
            from_knowledge_base=use_knowledge_base,
            sources=sources if use_knowledge_base else None
        )
        
        # 返回响应
        return jsonify({
            'success': True,
            'message': '聊天成功',
            'data': {
                'response': response,
                'sessionId': session_id,
                'sources': sources if use_knowledge_base else [],
                'model': {
                    'id': model.id,
                    'name': model.name,
                    'provider': model.provider
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"聊天失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'聊天失败: {str(e)}'
        }), 500

@chat_bp.route('/send-stream', methods=['POST'])
@login_required
def send_message_stream():
    """发送聊天消息（流式响应）"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        # 兼容前端发送的驼峰命名参数
        model_id = data.get('model_id') or data.get('modelId')
        knowledge_base_id = data.get('knowledge_base_id') or data.get('knowledgeBaseId')
        use_knowledge_base = data.get('use_knowledge_base', False) or data.get('useKnowledgeBase', False)
        session_id = data.get('session_id') or data.get('sessionId')  # 获取会话ID
        
        if not message:
            return jsonify({
                'success': False,
                'message': '消息内容不能为空'
            }), 400
        
        # 获取当前用户
        user_id = None
        if hasattr(request, 'current_user'):
            user_id = request.current_user.get('user_id')
        elif hasattr(request, 'user'):
            user_id = request.user.id
        else:
            # 如果没有用户信息，尝试从JWT中获取
            from flask_jwt_extended import get_jwt_identity
            user_id = get_jwt_identity()
        
        # 如果没有会话ID，创建新会话
        if not session_id:
            # 生成会话标题（使用消息的前20个字符）
            title = message[:20] + "..." if len(message) > 20 else message
            session = ChatService.create_session(
                user_id=user_id,
                title=title,
                model_id=model_id,
                knowledge_base_id=knowledge_base_id if use_knowledge_base else None
            )
            session_id = session.id
        else:
            # 验证会话是否存在
            session = ChatService.get_session_by_id(session_id, user_id)
            if not session:
                return jsonify({
                    'success': False,
                    'message': '聊天会话不存在或无权限'
                }), 404
        
        # 保存用户消息
        ChatService.add_message(
            session_id=session_id,
            content=message,
            message_type='user',
            role='user'
        )
        
        # 记录开始时间，用于计算响应时间
        start_time = time.time()
        
        # 获取对话模型
        model = None
        if model_id:
            model = ModelConfig.query.filter_by(id=model_id, type='chat', status='active').first()
        else:
            # 如果没有指定模型，使用默认对话模型
            model = ModelConfig.query.filter_by(type='chat', is_default=True, status='active').first()
        
        if not model:
            return jsonify({
                'success': False,
                'message': '未找到可用的对话模型'
            }), 400
        
        # 初始化向量管理器
        vector_manager = VectorManager()
        
        # 知识库检索
        context = ""
        sources = []
        if use_knowledge_base and knowledge_base_id:
            # 获取知识库信息
            kb = KnowledgeBase.query.filter_by(id=knowledge_base_id).first()
            if kb:
                # 更新向量管理器的嵌入模型
                vector_manager.embedding_model = kb.embedding_model
                
                # 获取知识库设置
                settings = KnowledgeBaseSettings.get_settings()
                
                # 检索知识库
                search_results = vector_manager.hybrid_search(
                    query=message,
                    kb_id=knowledge_base_id,
                    limit=5,
                    similarity_threshold=settings.similarity_threshold
                )
                
                if search_results:
                    # 构建上下文
                    context_parts = []
                    for result in search_results:
                        content = result.get('content', '')
                        title = result.get('title', '未知文档')
                        similarity = result.get('similarity', 0)
                        
                        context_parts.append(f"文档: {title}\n内容: {content}\n相似度: {similarity:.2f}\n")
                        sources.append({
                            'id': result.get('document_id', ''),
                            'title': title,
                            'content': content,
                            'similarity': similarity
                        })
                    
                    context = "\n".join(context_parts)
        
        # 构建系统提示
        system_prompt = model.system_prompt or "你是一个专业的医学助手，请根据提供的上下文回答用户的问题。如果上下文中没有相关信息，请基于你的专业知识回答。"
        
        if context:
            system_prompt = f"{system_prompt}\n\n请基于以下上下文信息回答用户的问题：\n\n{context}"
        
        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
        
        # 用于收集流式响应的完整内容
        full_response = ""
        
        def generate():
            nonlocal full_response
            
            # 发送初始信息
            start_data = {
                'type': 'start',
                'success': True,
                'data': {
                    'sessionId': session_id,
                    'model': {
                        'id': model.id,
                        'name': model.name,
                        'provider': model.provider
                    },
                    'sources': sources if use_knowledge_base else []
                }
            }
            logger.info(f"发送流式响应开始事件: {start_data}")  # 添加调试日志
            yield generate_stream_response(start_data)
            
            # 流式调用对话模型
            if model.provider == 'openai':
                for chunk in call_openai_model_stream(model, messages):
                    # 收集响应内容
                    if chunk.startswith('data: ') and not chunk.startswith('data: [DONE]'):
                        try:
                            chunk_data = json.loads(chunk[6:])  # 去掉 'data: ' 前缀
                            if 'data' in chunk_data and 'content' in chunk_data['data']:
                                full_response += chunk_data['data']['content']
                        except:
                            pass
                    yield chunk
            elif model.provider == 'ollama':
                for chunk in call_ollama_model_stream(model, messages):
                    # 收集响应内容
                    if chunk.startswith('data: ') and not chunk.startswith('data: [DONE]'):
                        try:
                            chunk_data = json.loads(chunk[6:])  # 去掉 'data: ' 前缀
                            if 'data' in chunk_data and 'content' in chunk_data['data']:
                                full_response += chunk_data['data']['content']
                        except:
                            pass
                    yield chunk
            elif model.provider == 'qianwen':
                for chunk in call_qianwen_model_stream(model, messages):
                    # 收集响应内容
                    if chunk.startswith('data: ') and not chunk.startswith('data: [DONE]'):
                        try:
                            chunk_data = json.loads(chunk[6:])  # 去掉 'data: ' 前缀
                            if 'data' in chunk_data and 'content' in chunk_data['data']:
                                full_response += chunk_data['data']['content']
                        except:
                            pass
                    yield chunk
            else:
                yield generate_stream_response({
                    'type': 'error',
                    'success': False,
                    'message': f'不支持的模型提供商: {model.provider}'
                })
                return
            
            # 计算响应时间
            response_time = time.time() - start_time
            
            # 保存AI回复
            if full_response:
                ChatService.add_message(
                    session_id=session_id,
                    content=full_response,
                    message_type='ai',
                    role='assistant',
                    model_response_time=response_time,
                    from_knowledge_base=use_knowledge_base,
                    sources=sources if use_knowledge_base else None
                )
            
            # 发送结束信息
            yield generate_stream_response({
                'type': 'end',
                'success': True
            })
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        logger.error(f"流式聊天失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'流式聊天失败: {str(e)}'
        }), 500

def call_chat_model(model: ModelConfig, messages: List[Dict[str, str]]) -> Optional[str]:
    """调用对话模型"""
    try:
        # 根据提供商调用不同的API
        if model.provider == 'openai':
            return call_openai_model(model, messages)
        elif model.provider == 'ollama':
            return call_ollama_model(model, messages)
        elif model.provider == 'qianwen':
            return call_qianwen_model(model, messages)
        else:
            logger.error(f"不支持的模型提供商: {model.provider}")
            return None
    except Exception as e:
        logger.error(f"调用对话模型失败: {str(e)}")
        return None

def call_openai_model(model: ModelConfig, messages: List[Dict[str, str]]) -> Optional[str]:
    """调用OpenAI模型"""
    try:
        api_url = model.api_endpoint or "https://api.openai.com/v1/chat/completions"
        if not api_url.endswith('/chat/completions'):
            api_url = f"{api_url.rstrip('/')}/chat/completions"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {model.api_key}'
        }
        
        payload = {
            'model': model.model_name,
            'messages': messages,
            'temperature': model.temperature or 0.7,
            'max_tokens': model.max_tokens or 1000
        }
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"调用OpenAI模型失败: {str(e)}")
        return None

def call_ollama_model(model: ModelConfig, messages: List[Dict[str, str]]) -> Optional[str]:
    """调用Ollama模型"""
    try:
        api_url = model.api_endpoint or "http://localhost:11434/api/chat"
        if not api_url.endswith('/api/chat'):
            api_url = f"{api_url.rstrip('/')}/api/chat"
        
        payload = {
            'model': model.model_name,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': model.temperature or 0.7,
                'num_predict': model.max_tokens or 1000
            }
        }
        
        response = requests.post(api_url, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        return data['message']['content']
    except Exception as e:
        logger.error(f"调用Ollama模型失败: {str(e)}")
        return None

def call_qianwen_model(model: ModelConfig, messages: List[Dict[str, str]]) -> Optional[str]:
    """调用千问模型"""
    try:
        api_url = model.api_endpoint or "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {model.api_key}'
        }
        
        payload = {
            'model': model.model_name,
            'input': {
                'messages': messages
            },
            'parameters': {
                'temperature': model.temperature or 0.7,
                'max_tokens': model.max_tokens or 1000
            }
        }
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        return data['output']['text']
    except Exception as e:
        logger.error(f"调用千问模型失败: {str(e)}")
        return None

def call_openai_model_stream(model: ModelConfig, messages: List[Dict[str, str]]):
    """流式调用OpenAI模型"""
    try:
        api_url = model.api_endpoint or "https://api.openai.com/v1/chat/completions"
        if not api_url.endswith('/chat/completions'):
            api_url = f"{api_url.rstrip('/')}/chat/completions"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {model.api_key}'
        }
        
        payload = {
            'model': model.model_name,
            'messages': messages,
            'temperature': model.temperature or 0.7,
            'max_tokens': model.max_tokens or 1000,
            'stream': True
        }
        
        response = requests.post(api_url, headers=headers, json=payload, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]  # 去掉 'data: ' 前缀
                    if data_str.strip() == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(data_str)
                        if 'choices' in data and len(data['choices']) > 0:
                            delta = data['choices'][0].get('delta', {})
                            if 'content' in delta:
                                content = delta['content']
                                yield generate_stream_response({
                                    'type': 'message',
                                    'content': content
                                })
                    except json.JSONDecodeError:
                        continue
                        
    except Exception as e:
        logger.error(f"流式调用OpenAI模型失败: {str(e)}")
        yield generate_stream_response({
            'type': 'error',
            'success': False,
            'message': f'流式调用OpenAI模型失败: {str(e)}'
        })

def call_ollama_model_stream(model: ModelConfig, messages: List[Dict[str, str]]):
    """流式调用Ollama模型"""
    try:
        api_url = model.api_endpoint or "http://localhost:11434/api/chat"
        if not api_url.endswith('/api/chat'):
            api_url = f"{api_url.rstrip('/')}/api/chat"
        
        payload = {
            'model': model.model_name,
            'messages': messages,
            'stream': True,
            'options': {
                'temperature': model.temperature or 0.7,
                'num_predict': model.max_tokens or 1000
            }
        }
        
        response = requests.post(api_url, json=payload, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if 'message' in data and 'content' in data['message']:
                        content = data['message']['content']
                        if content:
                            yield generate_stream_response({
                                'type': 'message',
                                'content': content
                            })
                    
                    if data.get('done', False):
                        break
                except json.JSONDecodeError:
                    continue
                    
    except Exception as e:
        logger.error(f"流式调用Ollama模型失败: {str(e)}")
        yield generate_stream_response({
            'type': 'error',
            'success': False,
            'message': f'流式调用Ollama模型失败: {str(e)}'
        })

def call_qianwen_model_stream(model: ModelConfig, messages: List[Dict[str, str]]):
    """流式调用千问模型"""
    try:
        api_url = model.api_endpoint or "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {model.api_key}'
        }
        
        payload = {
            'model': model.model_name,
            'input': {
                'messages': messages
            },
            'parameters': {
                'temperature': model.temperature or 0.7,
                'max_tokens': model.max_tokens or 1000,
                'incremental_output': True
            }
        }
        
        response = requests.post(api_url, headers=headers, json=payload, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if 'output' in data and 'text' in data['output']:
                        content = data['output']['text']
                        if content:
                            yield generate_stream_response({
                                'type': 'message',
                                'content': content
                            })
                    
                    if data.get('output', {}).get('finish_reason', '') == 'stop':
                        break
                except json.JSONDecodeError:
                    continue
                    
    except Exception as e:
        logger.error(f"流式调用千问模型失败: {str(e)}")
        yield generate_stream_response({
            'type': 'error',
            'success': False,
            'message': f'流式调用千问模型失败: {str(e)}'
        })