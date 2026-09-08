#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型管理路由
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.model import ModelConfig
from models.base import db
from utils.response import success_response, error_response
from utils.model_testing import test_model_connection
from utils.validators import validate_model_data

# 创建蓝图
models_bp = Blueprint('models', __name__, url_prefix='/api/models')

# 获取所有模型配置
@models_bp.route('/', methods=['GET'])
def get_models():
    """获取所有模型配置"""
    try:
        models = ModelConfig.query.all()
        return success_response({
            'models': [model.to_dict() for model in models]
        })
    except Exception as e:
        return error_response(f'获取模型配置失败: {str(e)}', 500)

# 获取单个模型配置
@models_bp.route('/<string:model_id>', methods=['GET'])
def get_model(model_id):
    """获取单个模型配置"""
    try:
        model = ModelConfig.query.get(model_id)
        if not model:
            return error_response(f'模型配置不存在', 404)
        
        return success_response({
            'model': model.to_dict()
        })
    except Exception as e:
        return error_response(f'获取模型配置失败: {str(e)}', 500)

# 创建新的模型配置
@models_bp.route('/', methods=['POST'])
def create_model():
    """创建新的模型配置"""
    try:
        data = request.get_json()
        
        # 验证数据
        errors = validate_model_data(data)
        if errors:
            return error_response('参数验证失败', 400, errors)
        
        # 创建模型配置
        new_model = ModelConfig(
            id=data.get('id') or datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3],  # 使用时间戳作为ID
            name=data.get('name'),
            provider=data.get('provider'),
            type=data.get('type'),
            model_name=data.get('modelName'),
            api_key=data.get('apiKey'),
            api_endpoint=data.get('apiEndpoint'),
            temperature=data.get('temperature'),
            max_tokens=data.get('maxTokens'),
            top_p=data.get('topP'),
            system_prompt=data.get('systemPrompt'),
            status=data.get('status', 'active'),
            is_default=data.get('isDefault', False),
            description=data.get('description')
        )
        
        # 如果设置为默认模型，取消其他模型的默认状态
        if new_model.is_default:
            ModelConfig.query.filter(ModelConfig.is_default == True).update({'is_default': False})
        
        db.session.add(new_model)
        db.session.commit()
        
        return success_response({
            'message': '模型配置创建成功',
            'model': new_model.to_dict()
        }, 201)
    except Exception as e:
        db.session.rollback()
        return error_response(f'创建模型配置失败: {str(e)}', 500)

# 更新模型配置
@models_bp.route('/<string:model_id>', methods=['PUT'])
def update_model(model_id):
    """更新模型配置"""
    try:
        # 获取要更新的模型
        model = ModelConfig.query.get(model_id)
        if not model:
            return error_response(f'模型配置不存在', 404)
        
        # 获取请求数据
        data = request.get_json()
        
        # 如果设置为默认模型，取消其他模型的默认状态
        if data.get('isDefault') and not model.is_default:
            ModelConfig.query.filter(ModelConfig.is_default == True).update({'is_default': False})
        
        # 更新模型字段（先转换字段名，再检查属性）
        field_map = {
            'modelName': 'model_name',
            'apiKey': 'api_key',
            'apiEndpoint': 'api_endpoint',
            'maxTokens': 'max_tokens',
            'topP': 'top_p',
            'systemPrompt': 'system_prompt',
            'isDefault': 'is_default',
            'createdAt': None,
            'updatedAt': None,
        }

        for field, value in data.items():
            mapped = field_map.get(field, field)
            if mapped is None:
                # 跳过这些字段，由数据库自动处理
                continue
            if hasattr(model, mapped):
                setattr(model, mapped, value)
        
        # 更新时间戳
        model.updated_at = datetime.utcnow()
        
        # 提交更改
        db.session.commit()
        
        return success_response({
            'message': '模型配置更新成功',
            'model': model.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return error_response(f'更新模型配置失败: {str(e)}', 500)

# 删除模型配置
@models_bp.route('/<string:model_id>', methods=['DELETE'])
def delete_model(model_id):
    """删除模型配置"""
    try:
        # 获取要删除的模型
        model = ModelConfig.query.get(model_id)
        if not model:
            return error_response(f'模型配置不存在', 404)
        
        # 检查是否为默认模型
        if model.is_default:
            return error_response('不能删除默认模型', 400)
        
        # 删除模型
        db.session.delete(model)
        db.session.commit()
        
        return success_response({
            'message': '模型配置删除成功'
        })
    except Exception as e:
        db.session.rollback()
        return error_response(f'删除模型配置失败: {str(e)}', 500)

# 测试模型连接
@models_bp.route('/<string:model_id>/test', methods=['POST'])
def test_model(model_id):
    """测试模型连接（真实调用）"""
    try:
        # 获取模型
        model = ModelConfig.query.get(model_id)
        if not model:
            return error_response(f'模型配置不存在', 404)

        # 更新状态为测试中
        model.status = 'testing'
        db.session.commit()

        # 执行真实测试
        result = test_model_connection(model)

        # 更新状态
        model.status = 'active' if result.get('success') else 'error'
        db.session.commit()

        return success_response({
            'testResult': {
                'success': result.get('success'),
                'responseTime': result.get('responseTime'),
                'errorMessage': result.get('errorMessage'),
                'sampleResponse': result.get('sampleResponse'),
            }
        })
    except Exception as e:
        # 更新状态为错误
        model = ModelConfig.query.get(model_id)
        if model:
            model.status = 'error'
            db.session.commit()

        return error_response(f'测试模型连接失败: {str(e)}', 500)

# 设置默认模型
@models_bp.route('/<string:model_id>/set-default', methods=['POST'])
def set_default_model(model_id):
    """设置默认模型"""
    try:
        # 获取要设置的模型
        model = ModelConfig.query.get(model_id)
        if not model:
            return error_response(f'模型配置不存在', 404)
        
        # 取消所有模型的默认状态
        ModelConfig.query.filter(ModelConfig.is_default == True).update({'is_default': False})
        
        # 设置当前模型为默认
        model.is_default = True
        model.updated_at = datetime.utcnow()
        
        # 提交更改
        db.session.commit()
        
        return success_response({
            'message': '默认模型设置成功',
            'model': model.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return error_response(f'设置默认模型失败: {str(e)}', 500)

# 获取默认模型
@models_bp.route('/default', methods=['GET'])
def get_default_model():
    """获取默认模型"""
    try:
        default_model = ModelConfig.query.filter_by(is_default=True).first()
        
        if not default_model:
            return success_response({
                'message': '没有设置默认模型',
                'model': None
            })
        
        return success_response({
            'model': default_model.to_dict()
        })
    except Exception as e:
        return error_response(f'获取默认模型失败: {str(e)}', 500)