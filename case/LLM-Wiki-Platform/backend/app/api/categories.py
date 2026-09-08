# 分类API
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.document_service import DocumentService
from app.utils.decorators import require_permission

def register_routes(bp):
    """注册分类路由"""
    
    @bp.route('/categories', methods=['GET'])
    @jwt_required()
    def get_categories():
        """获取分类列表"""
        categories = DocumentService.get_categories()
        return jsonify({'categories': categories})
    
    @bp.route('/categories/<int:category_id>', methods=['GET'])
    @jwt_required()
    def get_category(category_id):
        """获取分类详情"""
        category = DocumentService.get_category_by_id(category_id)
        if not category:
            return jsonify({'error': 'Category not found'}), 404
        
        return jsonify({'category': category.to_dict()})
    
    @bp.route('/categories', methods=['POST'])
    @jwt_required()
    @require_permission('admin')
    def create_category():
        """创建分类"""
        data = request.get_json()
        
        category, error = DocumentService.create_category(data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'category': category.to_dict()}), 201
    
    @bp.route('/categories/<int:category_id>', methods=['PUT'])
    @jwt_required()
    @require_permission('admin')
    def update_category(category_id):
        """更新分类"""
        data = request.get_json()
        
        category, error = DocumentService.update_category(category_id, data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'category': category.to_dict()})
    
    @bp.route('/categories/<int:category_id>', methods=['DELETE'])
    @jwt_required()
    @require_permission('admin')
    def delete_category(category_id):
        """删除分类"""
        success, error = DocumentService.delete_category(category_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': 'Category deleted successfully'})