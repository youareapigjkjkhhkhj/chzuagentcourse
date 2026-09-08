# 文档API
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.document_service import DocumentService
from app.utils.decorators import require_permission

def register_routes(bp):
    """注册文档路由"""
    
    @bp.route('/documents', methods=['GET'])
    @jwt_required()
    def get_documents():
        """获取文档列表"""
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        category_id = request.args.get('category_id', type=int)
        keyword = request.args.get('keyword')
        status = request.args.get('status', 'published')
        
        result = DocumentService.get_documents(
            page=page,
            per_page=per_page,
            category_id=category_id,
            keyword=keyword,
            status=status
        )
        
        return jsonify(result)
    
    @bp.route('/documents/<int:doc_id>', methods=['GET'])
    @jwt_required()
    def get_document(doc_id):
        """获取文档详情"""
        document = DocumentService.get_document_by_id(doc_id)
        if not document:
            return jsonify({'error': 'Document not found'}), 404
        
        # 增加查看次数
        DocumentService.increment_view_count(doc_id)
        
        return jsonify({'document': document.to_dict()})
    
    @bp.route('/documents', methods=['POST'])
    @jwt_required()
    @require_permission('editor')
    def create_document():
        """创建文档"""
        data = request.get_json()
        user_id = get_jwt_identity()
        
        document, error = DocumentService.create_document(data, user_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'document': document.to_dict()}), 201
    
    @bp.route('/documents/<int:doc_id>', methods=['PUT'])
    @jwt_required()
    @require_permission('editor')
    def update_document(doc_id):
        """更新文档"""
        data = request.get_json()
        user_id = get_jwt_identity()
        
        document, error = DocumentService.update_document(doc_id, data, user_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'document': document.to_dict()})
    
    @bp.route('/documents/<int:doc_id>', methods=['DELETE'])
    @jwt_required()
    @require_permission('editor')
    def delete_document(doc_id):
        """删除文档"""
        user_id = get_jwt_identity()
        
        success, error = DocumentService.delete_document(doc_id, user_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': 'Document deleted successfully'})
    
    @bp.route('/documents/search', methods=['GET'])
    @jwt_required()
    def search_documents():
        """搜索文档"""
        keyword = request.args.get('keyword', '')
        category_id = request.args.get('category_id', type=int)
        tags = request.args.getlist('tags')
        
        results = DocumentService.search_documents(keyword, category_id, tags)
        
        return jsonify({'results': results})