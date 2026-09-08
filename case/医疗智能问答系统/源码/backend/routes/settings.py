#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置管理路由
"""

from flask import Blueprint, request, current_app
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.settings import KnowledgeBaseSettings
from models.base import db
from utils.response import success_response, error_response
from utils.auth import login_required
from utils.vector_manager import VectorManager

# 创建蓝图
settings_bp = Blueprint('settings', __name__, url_prefix='/api/settings')


@settings_bp.route('/knowledge-base', methods=['GET'])
@login_required
def get_settings():
    """获取知识库设置"""
    try:
        current_app.logger.info("[Settings:get_settings] fetching knowledge base settings")
        
        # 获取默认设置（ID为'default'）
        settings = db.session.get(KnowledgeBaseSettings, 'default')
        
        # 如果不存在，创建默认设置
        if not settings:
            current_app.logger.info("[Settings:get_settings] creating default settings")
            
            # 使用环境变量中的数据库连接字符串和默认嵌入模型
            db_url = os.getenv('DATABASE_URL', '')
            default_embedding_model = os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')
            
            # 尝试从模型配置中获取默认模型的 API URL
            embedding_api_url = None
            try:
                from models.model import ModelConfig
                model_config = ModelConfig.query.filter_by(
                    model_name=default_embedding_model,
                    type='embedding'
                ).first()
                
                if model_config and model_config.api_endpoint:
                    embedding_api_url = model_config.api_endpoint
                    # 确保 URL 包含 /api/embeddings 路径
                    if not embedding_api_url.endswith('/api/embeddings') and not embedding_api_url.endswith('/embeddings'):
                        embedding_api_url = f"{embedding_api_url}/api/embeddings"
                    current_app.logger.info(f"[Settings:get_settings] using API URL from model config: {embedding_api_url}")
            except Exception as model_err:
                current_app.logger.warning(f"[Settings:get_settings] failed to get model config: {model_err}")
            
            # 如果没有从模型配置中获取到，使用环境变量
            if not embedding_api_url:
                embedding_api_url = os.getenv('EMBEDDINGS_API_URL', 'http://127.0.0.1:11434/api/embeddings')
            
            settings = KnowledgeBaseSettings(
                id='default',
                vector_db_type='pgvector',
                connection_string=db_url,
                embedding_model=default_embedding_model,
                embedding_api_url=embedding_api_url,
                embedding_dimension=1536,
                chunk_size=1000,
                chunk_overlap=200,
                similarity_threshold=0.7,
                max_search_results=10
            )
            db.session.add(settings)
            db.session.commit()
        
        current_app.logger.info(f"[Settings:get_settings] settings retrieved: {settings.to_dict()}")
        
        return success_response({
            'settings': settings.to_dict()
        })
        
    except Exception as e:
        current_app.logger.exception(f"[Settings:get_settings] error: {e}")
        return error_response(f'获取设置失败: {str(e)}', status_code=500)


@settings_bp.route('/knowledge-base', methods=['PUT'])
@login_required
def update_settings():
    """更新知识库设置"""
    try:
        data = request.get_json()
        current_app.logger.info(f"[Settings:update_settings] data={data}")
        
        # 获取或创建设置
        settings = db.session.get(KnowledgeBaseSettings, 'default')
        
        if not settings:
            current_app.logger.info("[Settings:update_settings] creating new settings")
            settings = KnowledgeBaseSettings(id='default')
            db.session.add(settings)
        
        # 更新字段
        if 'vectorDbType' in data:
            settings.vector_db_type = data['vectorDbType']
        
        if 'connectionString' in data:
            settings.connection_string = data['connectionString']
        
        if 'embeddingModel' in data:
            settings.embedding_model = data['embeddingModel']
            
            # 如果更改了嵌入模型，尝试从模型配置中获取 API URL
            if 'embeddingApiUrl' not in data:
                try:
                    from models.model import ModelConfig
                    model_config = ModelConfig.query.filter_by(
                        model_name=data['embeddingModel'],
                        type='embedding'
                    ).first()
                    
                    if model_config and model_config.api_endpoint:
                        api_url = model_config.api_endpoint
                        # 确保 URL 包含 /api/embeddings 路径
                        if not api_url.endswith('/api/embeddings') and not api_url.endswith('/embeddings'):
                            api_url = f"{api_url}/api/embeddings"
                        settings.embedding_api_url = api_url
                        current_app.logger.info(f"[Settings:update_settings] auto-set API URL from model config: {api_url}")
                except Exception as model_err:
                    current_app.logger.warning(f"[Settings:update_settings] failed to get model config: {model_err}")
        
        if 'embeddingApiUrl' in data:
            settings.embedding_api_url = data['embeddingApiUrl']
        
        if 'embeddingDimension' in data:
            # 验证维度是否为正整数
            dimension = data['embeddingDimension']
            if not isinstance(dimension, int) or dimension <= 0:
                return error_response('向量维度必须是正整数', status_code=400)
            settings.embedding_dimension = dimension
        
        if 'chunkSize' in data:
            # 验证块大小
            chunk_size = data['chunkSize']
            if not isinstance(chunk_size, int) or chunk_size <= 0:
                return error_response('文本块大小必须是正整数', status_code=400)
            settings.chunk_size = chunk_size
        
        if 'chunkOverlap' in data:
            # 验证重叠大小
            chunk_overlap = data['chunkOverlap']
            if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
                return error_response('文本块重叠必须是非负整数', status_code=400)
            settings.chunk_overlap = chunk_overlap
        
        if 'similarityThreshold' in data:
            # 验证相似度阈值
            threshold = data['similarityThreshold']
            if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
                return error_response('相似度阈值必须在0到1之间', status_code=400)
            settings.similarity_threshold = float(threshold)
        
        if 'maxSearchResults' in data:
            # 验证最大搜索结果数
            max_results = data['maxSearchResults']
            if not isinstance(max_results, int) or max_results <= 0:
                return error_response('最大搜索结果数必须是正整数', status_code=400)
            settings.max_search_results = max_results
        
        # 更新时间戳
        settings.updated_at = datetime.utcnow()
        
        # 提交更改
        db.session.commit()
        
        current_app.logger.info(f"[Settings:update_settings] settings updated: {settings.to_dict()}")
        
        return success_response({
            'message': '设置更新成功',
            'settings': settings.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[Settings:update_settings] error: {e}")
        return error_response(f'更新设置失败: {str(e)}', status_code=500)



@settings_bp.route('/test-embedding', methods=['POST'])
@login_required
def test_embedding():
    """测试嵌入模型连接"""
    try:
        data = request.get_json() or {}
        current_app.logger.info(f"[Settings:test_embedding] testing embedding model")
        
        # 获取测试参数
        embedding_model = data.get('embeddingModel')
        embedding_api_url = data.get('embeddingApiUrl')
        test_text = data.get('testText', '这是一个测试文本')
        
        # 如果没有提供模型名称，从设置中获取
        if not embedding_model:
            settings = db.session.get(KnowledgeBaseSettings, 'default')
            if settings and settings.embedding_model:
                embedding_model = settings.embedding_model
                embedding_api_url = embedding_api_url or settings.embedding_api_url
        
        # 如果还是没有 API URL，尝试从模型配置中获取
        if embedding_model and not embedding_api_url:
            try:
                from models.model import ModelConfig
                model_config = ModelConfig.query.filter_by(
                    model_name=embedding_model,
                    type='embedding'
                ).first()
                
                if model_config and model_config.api_endpoint:
                    embedding_api_url = model_config.api_endpoint
                    # 确保 URL 包含 /api/embeddings 路径
                    if not embedding_api_url.endswith('/api/embeddings') and not embedding_api_url.endswith('/embeddings'):
                        embedding_api_url = f"{embedding_api_url}/api/embeddings"
                    current_app.logger.info(f"[Settings:test_embedding] using API URL from model config: {embedding_api_url}")
            except Exception as model_err:
                current_app.logger.warning(f"[Settings:test_embedding] failed to get model config: {model_err}")
        
        # 最后的回退：使用环境变量
        if not embedding_model:
            embedding_model = os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')
        if not embedding_api_url:
            embedding_api_url = os.getenv('EMBEDDINGS_API_URL', 'http://127.0.0.1:11434/api/embeddings')
        
        current_app.logger.info(
            f"[Settings:test_embedding] model={embedding_model}, "
            f"api_url={embedding_api_url}, test_text='{test_text[:50]}...'"
        )
        
        # 创建临时向量管理器进行测试
        import requests
        import json
        
        # 测试连接和模型可用性
        try:
            headers = {'Content-Type': 'application/json'}
            
            # 尝试 OpenAI 风格
            payload_openai = {
                'model': embedding_model,
                'input': test_text
            }
            
            response = requests.post(
                embedding_api_url,
                headers=headers,
                data=json.dumps(payload_openai),
                timeout=10
            )
            
            if response.status_code == 200:
                data_resp = response.json()
                
                # 检查响应格式
                embedding = None
                if isinstance(data_resp, dict):
                    if 'data' in data_resp and data_resp['data']:
                        embedding = data_resp['data'][0].get('embedding')
                    elif 'embedding' in data_resp:
                        embedding = data_resp['embedding']
                
                if embedding and isinstance(embedding, list):
                    current_app.logger.info(
                        f"[Settings:test_embedding] OpenAI style success, "
                        f"dimension={len(embedding)}"
                    )
                    return success_response({
                        'message': '嵌入模型连接成功',
                        'available': True,
                        'model': embedding_model,
                        'apiUrl': embedding_api_url,
                        'dimension': len(embedding),
                        'apiStyle': 'OpenAI',
                        'testText': test_text
                    })
            
            # 尝试 Ollama 风格
            payload_ollama = {
                'model': embedding_model,
                'prompt': test_text
            }
            
            response2 = requests.post(
                embedding_api_url,
                headers=headers,
                data=json.dumps(payload_ollama),
                timeout=10
            )
            
            if response2.status_code == 200:
                data_resp2 = response2.json()
                
                embedding2 = None
                if isinstance(data_resp2, dict):
                    if 'embedding' in data_resp2:
                        embedding2 = data_resp2['embedding']
                    elif 'data' in data_resp2 and data_resp2['data']:
                        embedding2 = data_resp2['data'][0].get('embedding')
                
                if embedding2 and isinstance(embedding2, list):
                    current_app.logger.info(
                        f"[Settings:test_embedding] Ollama style success, "
                        f"dimension={len(embedding2)}"
                    )
                    return success_response({
                        'message': '嵌入模型连接成功',
                        'available': True,
                        'model': embedding_model,
                        'apiUrl': embedding_api_url,
                        'dimension': len(embedding2),
                        'apiStyle': 'Ollama',
                        'testText': test_text
                    })
            
            # 两种风格都失败
            error_msg = f"API 响应格式不正确。OpenAI 风格状态码: {response.status_code}, Ollama 风格状态码: {response2.status_code}"
            current_app.logger.warning(f"[Settings:test_embedding] {error_msg}")
            
            return success_response({
                'message': '嵌入模型不可用',
                'available': False,
                'model': embedding_model,
                'apiUrl': embedding_api_url,
                'error': error_msg,
                'details': {
                    'openai_status': response.status_code,
                    'ollama_status': response2.status_code
                }
            })
            
        except requests.exceptions.Timeout:
            error_msg = '连接超时，请检查 API 地址是否正确'
            current_app.logger.warning(f"[Settings:test_embedding] {error_msg}")
            return success_response({
                'message': '嵌入模型不可用',
                'available': False,
                'model': embedding_model,
                'apiUrl': embedding_api_url,
                'error': error_msg
            })
            
        except requests.exceptions.ConnectionError:
            error_msg = '无法连接到 API，请检查服务是否运行'
            current_app.logger.warning(f"[Settings:test_embedding] {error_msg}")
            return success_response({
                'message': '嵌入模型不可用',
                'available': False,
                'model': embedding_model,
                'apiUrl': embedding_api_url,
                'error': error_msg
            })
            
        except Exception as e:
            error_msg = f'测试失败: {str(e)}'
            current_app.logger.error(f"[Settings:test_embedding] {error_msg}")
            return success_response({
                'message': '嵌入模型不可用',
                'available': False,
                'model': embedding_model,
                'apiUrl': embedding_api_url,
                'error': error_msg
            })
        
    except Exception as e:
        current_app.logger.exception(f"[Settings:test_embedding] error: {e}")
        return error_response(f'测试嵌入模型失败: {str(e)}', status_code=500)
