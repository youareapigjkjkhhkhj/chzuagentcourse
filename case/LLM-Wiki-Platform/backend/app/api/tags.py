# 标签API
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.document_service import DocumentService
from app.utils.decorators import require_permission

def register_routes(bp):
    """注册标签路由"""
    
    @bp.route('/tags', methods=['GET'])
    @jwt_required()
    def get_tags():
        """获取标签列表"""
        tags = DocumentService.get_tags()
        return jsonify({'tags': tags})
    
    @bp.route('/tags/<int:tag_id>', methods=['GET'])
    @jwt_required()
    def get_tag(tag_id):
        """获取标签详情"""
        tag = DocumentService.get_tag_by_id(tag_id)
        if not tag:
            return jsonify({'error': 'Tag not found'}), 404
        
        return jsonify({'tag': tag.to_dict()})
    
    @bp.route('/tags', methods=['POST'])
    @jwt_required()
    @require_permission('admin')
    def create_tag():
        """创建标签"""
        data = request.get_json()
        
        tag, error = DocumentService.create_tag(data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'tag': tag.to_dict()}), 201
    
    @bp.route('/tags/<int:tag_id>', methods=['PUT'])
    @jwt_required()
    @require_permission('admin')
    def update_tag(tag_id):
        """更新标签"""
        data = request.get_json()
        
        tag, error = DocumentService.update_tag(tag_id, data)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'tag': tag.to_dict()})
    
    @bp.route('/tags/<int:tag_id>', methods=['DELETE'])
    @jwt_required()
    @require_permission('admin')
    def delete_tag(tag_id):
        """删除标签"""
        success, error = DocumentService.delete_tag(tag_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': 'Tag deleted successfully'})