#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库管理路由 - 新的 pgvector 实现
"""

from flask import Blueprint, request, current_app
from datetime import datetime
from werkzeug.utils import secure_filename
import sys
import os
import tempfile
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.knowledge_base import KnowledgeBase
from models.document import Document
from models.base import db
from utils.response import success_response, error_response, validate_required_fields
from utils.auth import login_required, get_current_user
from utils.file_processor import FileProcessor
from utils.vector_manager import get_vector_manager

# 创建蓝图
kb_bp = Blueprint('kb', __name__, url_prefix='/api/kb')


@kb_bp.route('', methods=['GET'])
@login_required
def get_knowledge_bases():
    """获取知识库列表"""
    try:
        # 获取查询参数
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        
        current_app.logger.info(
            f"[KB:get_knowledge_bases] page={page}, per_page={per_page}, "
            f"search='{search}', status='{status}'"
        )
        
        # 构建查询
        query = KnowledgeBase.query
        
        # 搜索过滤
        if search:
            query = query.filter(
                db.or_(
                    KnowledgeBase.name.contains(search),
                    KnowledgeBase.description.contains(search)
                )
            )
        
        # 状态过滤
        if status:
            query = query.filter(KnowledgeBase.status == status)
        
        # 排序（按更新时间倒序）
        query = query.order_by(KnowledgeBase.updated_at.desc())
        
        # 分页
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        knowledge_bases = pagination.items
        total = pagination.total
        
        current_app.logger.info(
            f"[KB:get_knowledge_bases] found {total} knowledge bases"
        )
        
        return success_response({
            'knowledgeBases': [kb.to_dict(include_stats=True) for kb in knowledge_bases],
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:get_knowledge_bases] error: {e}")
        return error_response(f'获取知识库列表失败: {str(e)}', status_code=500)


@kb_bp.route('', methods=['POST'])
@login_required
def create_knowledge_base():
    """创建知识库"""
    try:
        data = request.get_json()
        current_app.logger.info(f"[KB:create_knowledge_base] data={data}")
        
        # 验证必需字段
        is_valid, missing_fields = validate_required_fields(data, ['name'])
        if not is_valid:
            return error_response(
                f'缺少必需字段: {", ".join(missing_fields)}',
                status_code=400
            )
        
        # 获取当前用户
        current_user = get_current_user()
        if not current_user:
            return error_response('用户未认证', status_code=401)
        
        # 生成ID
        kb_id = data.get('id') or datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]
        
        # 创建知识库
        kb = KnowledgeBase(
            id=kb_id,
            name=data.get('name'),
            description=data.get('description', ''),
            embedding_model=data.get('embeddingModel'),
            status=data.get('status', 'active'),
            created_by=current_user.get('username', '未知用户')
        )
        
        db.session.add(kb)
        db.session.commit()
        
        current_app.logger.info(
            f"[KB:create_knowledge_base] created kb_id={kb.id}, name='{kb.name}'"
        )
        
        return success_response(
            {
                'message': '知识库创建成功',
                'knowledgeBase': kb.to_dict(include_stats=True)
            },
            status_code=201
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:create_knowledge_base] error: {e}")
        return error_response(f'创建知识库失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>', methods=['GET'])
@login_required
def get_knowledge_base(kb_id):
    """获取知识库详情"""
    try:
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        current_app.logger.info(f"[KB:get_knowledge_base] kb_id={kb_id}")
        
        return success_response({
            'knowledgeBase': kb.to_dict(include_stats=True)
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:get_knowledge_base] error: {e}")
        return error_response(f'获取知识库详情失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>', methods=['PUT'])
@login_required
def update_knowledge_base(kb_id):
    """更新知识库"""
    try:
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        data = request.get_json()
        current_app.logger.info(f"[KB:update_knowledge_base] kb_id={kb_id}, data={data}")
        
        # 更新字段
        if 'name' in data:
            kb.name = data['name']
        if 'description' in data:
            kb.description = data['description']
        if 'embeddingModel' in data:
            kb.embedding_model = data['embeddingModel']
        if 'status' in data:
            kb.status = data['status']
        
        kb.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        current_app.logger.info(f"[KB:update_knowledge_base] updated kb_id={kb_id}")
        
        return success_response({
            'message': '知识库更新成功',
            'knowledgeBase': kb.to_dict(include_stats=True)
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:update_knowledge_base] error: {e}")
        return error_response(f'更新知识库失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>', methods=['DELETE'])
@login_required
def delete_knowledge_base(kb_id):
    """删除知识库"""
    try:
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取文档数量用于日志
        doc_count = kb.documents.count()
        
        current_app.logger.info(
            f"[KB:delete_knowledge_base] deleting kb_id={kb_id}, "
            f"name='{kb.name}', doc_count={doc_count}"
        )
        
        # 删除知识库（级联删除文档和向量）
        db.session.delete(kb)
        db.session.commit()
        
        current_app.logger.info(f"[KB:delete_knowledge_base] deleted kb_id={kb_id}")
        
        return success_response({
            'message': f'知识库已删除（包含 {doc_count} 个文档）'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:delete_knowledge_base] error: {e}")
        return error_response(f'删除知识库失败: {str(e)}', status_code=500)



@kb_bp.route('/<string:kb_id>/stats', methods=['GET'])
@login_required
def get_knowledge_base_stats(kb_id):
    """获取知识库统计信息"""
    try:
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        current_app.logger.info(f"[KB:get_knowledge_base_stats] kb_id={kb_id}")
        
        # 文档统计
        total_documents = kb.documents.count()
        published_documents = kb.documents.filter_by(status='published').count()
        draft_documents = kb.documents.filter_by(status='draft').count()
        processing_documents = kb.documents.filter_by(status='processing').count()
        failed_documents = kb.documents.filter_by(status='failed').count()
        
        # 向量统计
        total_vectors = db.session.query(db.func.sum(Document.chunk_count)).filter(
            Document.kb_id == kb_id
        ).scalar() or 0
        
        # 按分类统计
        category_stats = db.session.query(
            Document.category,
            db.func.count(Document.id)
        ).filter(
            Document.kb_id == kb_id
        ).group_by(Document.category).all()
        
        category_dict = {cat: count for cat, count in category_stats if cat}
        
        # 向量状态统计
        vector_status_stats = db.session.query(
            Document.vector_status,
            db.func.count(Document.id)
        ).filter(
            Document.kb_id == kb_id
        ).group_by(Document.vector_status).all()
        
        vector_status_dict = {status: count for status, count in vector_status_stats}
        
        stats = {
            'totalDocuments': total_documents,
            'publishedDocuments': published_documents,
            'draftDocuments': draft_documents,
            'processingDocuments': processing_documents,
            'failedDocuments': failed_documents,
            'totalVectors': int(total_vectors),
            'categoryStats': category_dict,
            'vectorStatusStats': vector_status_dict
        }
        
        current_app.logger.info(
            f"[KB:get_knowledge_base_stats] kb_id={kb_id}, stats={stats}"
        )
        
        return success_response({
            'stats': stats
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:get_knowledge_base_stats] error: {e}")
        return error_response(f'获取统计信息失败: {str(e)}', status_code=500)


# ==================== 文档管理接口 ====================

@kb_bp.route('/<string:kb_id>/documents', methods=['GET'])
@login_required
def get_documents(kb_id):
    """获取文档列表"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取查询参数
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '')
        status = request.args.get('status', '')
        category = request.args.get('category', '')
        
        current_app.logger.info(
            f"[KB:get_documents] kb_id={kb_id}, page={page}, per_page={per_page}, "
            f"search='{search}', status='{status}', category='{category}'"
        )
        
        # 构建查询
        query = Document.query.filter(Document.kb_id == kb_id)
        
        # 搜索过滤
        if search:
            query = query.filter(
                db.or_(
                    Document.title.contains(search),
                    Document.content.contains(search)
                )
            )
        
        # 状态过滤
        if status:
            query = query.filter(Document.status == status)
        
        # 分类过滤
        if category:
            query = query.filter(Document.category == category)
        
        # 排序（按更新时间倒序）
        query = query.order_by(Document.updated_at.desc())
        
        # 分页
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        documents = pagination.items
        total = pagination.total
        
        current_app.logger.info(
            f"[KB:get_documents] found {total} documents in kb_id={kb_id}"
        )
        
        return success_response({
            'documents': [doc.to_dict() for doc in documents],
            'pagination': {
                'page': page,
                'perPage': per_page,
                'total': total,
                'pages': pagination.pages,
                'hasNext': pagination.has_next,
                'hasPrev': pagination.has_prev
            }
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:get_documents] error: {e}")
        return error_response(f'获取文档列表失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/documents', methods=['POST'])
@login_required
def create_document(kb_id):
    """创建文档（手动录入）"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        data = request.get_json()
        current_app.logger.info(f"[KB:create_document] kb_id={kb_id}, data={data}")
        
        # 验证必需字段
        is_valid, missing_fields = validate_required_fields(data, ['title', 'content'])
        if not is_valid:
            return error_response(
                f'缺少必需字段: {", ".join(missing_fields)}',
                status_code=400
            )
        
        # 获取当前用户
        current_user = get_current_user()
        
        # 生成ID
        doc_id = data.get('id') or datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]
        
        # 处理标签
        import json
        tags = data.get('tags', [])
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)
        
        # 创建文档
        doc = Document(
            id=doc_id,
            kb_id=kb_id,
            title=data.get('title'),
            content=data.get('content'),
            category=data.get('category'),
            tags=tags,
            author=current_user.get('username') if current_user else data.get('author'),
            status=data.get('status', 'draft'),
            views=0,
            chunk_count=0,
            vector_status='pending'
        )
        
        db.session.add(doc)
        db.session.commit()
        
        current_app.logger.info(
            f"[KB:create_document] created doc_id={doc.id}, title='{doc.title}' in kb_id={kb_id}"
        )
        
        # 如果状态为 published，触发向量化
        if doc.status == 'published':
            from utils.vector_manager import get_vector_manager
            try:
                vector_manager = get_vector_manager()
                success = vector_manager.process_document(doc, kb)
                db.session.commit()
                
                if success:
                    current_app.logger.info(f"[KB:create_document] vectorized doc_id={doc.id}")
                else:
                    current_app.logger.warning(f"[KB:create_document] vectorization failed for doc_id={doc.id}")
            except Exception as ve:
                current_app.logger.error(f"[KB:create_document] vectorization error: {ve}")
                # 不影响文档创建，继续返回成功
        
        return success_response(
            {
                'message': '文档创建成功',
                'document': doc.to_dict()
            },
            status_code=201
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:create_document] error: {e}")
        return error_response(f'创建文档失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/documents/<string:doc_id>', methods=['GET'])
@login_required
def get_document(kb_id, doc_id):
    """获取文档详情"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取文档
        doc = db.session.get(Document, doc_id)
        if not doc or doc.kb_id != kb_id:
            return error_response('文档不存在', status_code=404)
        
        # 增加浏览次数
        doc.views += 1
        db.session.commit()
        
        current_app.logger.info(f"[KB:get_document] kb_id={kb_id}, doc_id={doc_id}")
        
        return success_response({
            'document': doc.to_dict()
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:get_document] error: {e}")
        return error_response(f'获取文档详情失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/documents/<string:doc_id>', methods=['PUT'])
@login_required
def update_document(kb_id, doc_id):
    """更新文档"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取文档
        doc = db.session.get(Document, doc_id)
        if not doc or doc.kb_id != kb_id:
            return error_response('文档不存在', status_code=404)
        
        data = request.get_json()
        current_app.logger.info(f"[KB:update_document] kb_id={kb_id}, doc_id={doc_id}, data={data}")
        
        # 记录旧状态
        old_status = doc.status
        old_content = doc.content
        
        # 更新字段
        if 'title' in data:
            doc.title = data['title']
        if 'content' in data:
            doc.content = data['content']
        if 'category' in data:
            doc.category = data['category']
        if 'tags' in data:
            import json
            tags = data['tags']
            if isinstance(tags, list):
                tags = json.dumps(tags, ensure_ascii=False)
            doc.tags = tags
        if 'author' in data:
            doc.author = data['author']
        if 'status' in data:
            doc.status = data['status']
        
        doc.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        current_app.logger.info(f"[KB:update_document] updated doc_id={doc_id}")
        
        # 如果状态变为 published 或内容有变化，重新向量化
        should_vectorize = False
        if old_status != 'published' and doc.status == 'published':
            should_vectorize = True
            current_app.logger.info(f"[KB:update_document] status changed to published, will vectorize")
        elif doc.status == 'published' and old_content != doc.content:
            should_vectorize = True
            current_app.logger.info(f"[KB:update_document] content changed, will re-vectorize")
        
        if should_vectorize:
            from utils.vector_manager import get_vector_manager
            try:
                vector_manager = get_vector_manager()
                success = vector_manager.process_document(doc, kb)
                db.session.commit()
                
                if success:
                    current_app.logger.info(f"[KB:update_document] vectorized doc_id={doc.id}")
                else:
                    current_app.logger.warning(f"[KB:update_document] vectorization failed for doc_id={doc.id}")
            except Exception as ve:
                current_app.logger.error(f"[KB:update_document] vectorization error: {ve}")
        
        return success_response({
            'message': '文档更新成功',
            'document': doc.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:update_document] error: {e}")
        return error_response(f'更新文档失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/documents/<string:doc_id>', methods=['DELETE'])
@login_required
def delete_document(kb_id, doc_id):
    """删除文档"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取文档
        doc = db.session.get(Document, doc_id)
        if not doc or doc.kb_id != kb_id:
            return error_response('文档不存在', status_code=404)
        
        current_app.logger.info(
            f"[KB:delete_document] deleting doc_id={doc_id}, title='{doc.title}' from kb_id={kb_id}"
        )
        
        # 删除向量数据
        from utils.vector_manager import get_vector_manager
        try:
            vector_manager = get_vector_manager()
            vector_manager.delete_document_vectors(doc_id)
            current_app.logger.info(f"[KB:delete_document] deleted vectors for doc_id={doc_id}")
        except Exception as ve:
            current_app.logger.error(f"[KB:delete_document] failed to delete vectors: {ve}")
            # 继续删除文档
        
        # 删除文档
        db.session.delete(doc)
        db.session.commit()
        
        current_app.logger.info(f"[KB:delete_document] deleted doc_id={doc_id}")
        
        return success_response({
            'message': '文档已删除'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:delete_document] error: {e}")
        return error_response(f'删除文档失败: {str(e)}', status_code=500)


# ==================== 文件上传接口 ====================

@kb_bp.route('/<string:kb_id>/documents/upload', methods=['POST'])
@login_required
def upload_document(kb_id):
    """上传单个文件"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 检查是否有文件
        if 'file' not in request.files:
            return error_response('未找到上传文件', status_code=400)
        
        file = request.files['file']
        
        if file.filename == '':
            return error_response('文件名为空', status_code=400)
        
        # 获取其他参数
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '')
        tags_str = request.form.get('tags', '[]')
        status = request.form.get('status', 'draft')
        
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        
        current_app.logger.info(
            f"[KB:upload_document] kb_id={kb_id}, filename='{file.filename}', "
            f"category='{category}', status='{status}'"
        )
        
        # 保存文件到临时目录
        filename = secure_filename(file.filename)
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}")
        
        try:
            file.save(temp_path)
            file_size = os.path.getsize(temp_path)
            
            # 获取文件类型 - 改进的扩展名提取逻辑
            original_filename = file.filename
            filename = secure_filename(original_filename)
            
            # 尝试多种方法获取文件扩展名
            file_ext = None
            
            # 方法1：标准方法
            if '.' in filename:
                file_ext = os.path.splitext(filename)[1][1:].lower()
            
            # 方法2：如果标准方法失败，尝试从原始文件名获取
            if not file_ext and '.' in original_filename:
                file_ext = os.path.splitext(original_filename)[1][1:].lower()
            
            # 方法3：如果还是没有，检查文件MIME类型
            if not file_ext and hasattr(file, 'content_type'):
                mime_type = file.content_type
                if mime_type:
                    mime_to_ext = {
                        'text/plain': 'txt',
                        'text/markdown': 'md',
                        'application/pdf': 'pdf',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx'
                    }
                    file_ext = mime_to_ext.get(mime_type, '')
            
            # 如果仍然没有扩展名，报错
            if not file_ext:
                current_app.logger.error(f"[KB:upload_document] 无法确定文件扩展名: 原始文件名={original_filename}, 处理后文件名={filename}")
                return error_response("无法确定文件类型，请确保文件有正确的扩展名", status_code=400)
            
            current_app.logger.info(f"[KB:upload_document] 原始文件名: {original_filename}, 处理后文件名: {filename}, 文件扩展名: {file_ext}")
            
            # 处理文件
            file_processor = FileProcessor()
            
            # 验证文件
            is_valid, error_msg = file_processor.validate_file(temp_path, file_ext)
            current_app.logger.info(f"[KB:upload_document] 文件验证结果: {is_valid}, 错误信息: {error_msg}")
            if not is_valid:
                return error_response(error_msg, status_code=400)
            
            # 提取文本内容
            content = file_processor.extract_text(temp_path, file_ext)
            
            if not content or not content.strip():
                return error_response('文件中未提取到任何文本内容', status_code=422)
            
            # 获取当前用户
            current_user = get_current_user()
            
            # 生成文档ID
            doc_id = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]
            
            # 创建文档
            doc = Document(
                id=doc_id,
                kb_id=kb_id,
                title=title if title else os.path.splitext(filename)[0],  # 优先使用用户提供的标题，否则使用文件名（不含扩展名）
                content=content,
                category=category,
                tags=json.dumps(tags, ensure_ascii=False) if tags else None,
                author=current_user.get('username') if current_user else None,
                status=status,
                file_name=filename,
                file_type=file_ext,
                file_size=file_size,
                views=0,
                chunk_count=0,
                vector_status='pending'
            )
            
            db.session.add(doc)
            db.session.commit()
            
            current_app.logger.info(
                f"[KB:upload_document] created doc_id={doc.id}, title='{doc.title}' from file '{filename}'"
            )
            
            # 如果状态为 published，触发向量化
            if doc.status == 'published':
                try:
                    vector_manager = get_vector_manager()
                    success = vector_manager.process_document(doc, kb)
                    db.session.commit()
                    
                    if success:
                        current_app.logger.info(f"[KB:upload_document] vectorized doc_id={doc.id}")
                    else:
                        current_app.logger.warning(f"[KB:upload_document] vectorization failed for doc_id={doc.id}")
                except Exception as ve:
                    current_app.logger.error(f"[KB:upload_document] vectorization error: {ve}")
            
            return success_response(
                {
                    'message': '文件上传成功',
                    'document': doc.to_dict()
                },
                status_code=201
            )
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    current_app.logger.info(f"[KB:upload_document] cleaned up temp file: {temp_path}")
                except Exception as e:
                    current_app.logger.warning(f"[KB:upload_document] failed to clean up temp file: {e}")
        
    except ValueError as ve:
        current_app.logger.error(f"[KB:upload_document] validation error: {ve}")
        return error_response(str(ve), status_code=400)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:upload_document] error: {e}")
        return error_response(f'文件上传失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/documents/upload-zip', methods=['POST'])
@login_required
def upload_zip(kb_id):
    """上传 ZIP 文件批量导入"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 检查是否有文件
        if 'file' not in request.files:
            return error_response('未找到上传文件', status_code=400)
        
        file = request.files['file']
        
        if file.filename == '':
            return error_response('文件名为空', status_code=400)
        
        # 验证是否为 ZIP 或 TAR.GZ 文件
        filename_lower = file.filename.lower()
        if not (filename_lower.endswith('.zip') or filename_lower.endswith('.tar.gz')):
            return error_response('只支持 ZIP 或 TAR.GZ 格式的压缩包。支持的格式: .zip, .tar.gz', status_code=400)
        
        # 获取其他参数
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '')
        tags_str = request.form.get('tags', '[]')
        status = request.form.get('status', 'draft')
        
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        
        current_app.logger.info(
            f"[KB:upload_zip] kb_id={kb_id}, filename='{file.filename}', "
            f"category='{category}', status='{status}'"
        )
        
        # 保存 ZIP 文件到临时目录
        filename = secure_filename(file.filename)
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}")
        
        try:
            file.save(zip_path)
            
            # 验证 ZIP/TAR.GZ 文件
            file_processor = FileProcessor()
            is_valid, error_msg = file_processor.validate_zip_file(zip_path)
            if not is_valid:
                return error_response(error_msg, status_code=400)
            
            # 处理 ZIP 文件
            file_results = file_processor.process_zip(zip_path, kb_id)
            
            if not file_results:
                return error_response('ZIP 文件中没有可处理的文件', status_code=422)
            
            # 获取当前用户
            current_user = get_current_user()
            
            # 批量创建文档
            created_docs = []
            failed_files = []
            
            for file_result in file_results:
                if not file_result['success']:
                    failed_files.append({
                        'fileName': file_result['file_name'],
                        'error': file_result['error']
                    })
                    continue
                
                try:
                    # 生成文档ID
                    doc_id = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]
                    
                    # 创建文档
                    doc = Document(
                        id=doc_id,
                        kb_id=kb_id,
                        title=title if title else os.path.splitext(file_result['file_name'])[0],
                        content=file_result['content'],
                        category=category,
                        tags=json.dumps(tags, ensure_ascii=False) if tags else None,
                        author=current_user.get('username') if current_user else None,
                        status=status,
                        file_name=file_result['file_name'],
                        file_type=file_result['file_type'],
                        file_size=file_result.get('file_size', 0),
                        views=0,
                        chunk_count=0,
                        vector_status='pending'
                    )
                    
                    db.session.add(doc)
                    created_docs.append(doc)
                    
                except Exception as e:
                    current_app.logger.error(
                        f"[KB:upload_zip] failed to create document for {file_result['file_name']}: {e}"
                    )
                    failed_files.append({
                        'fileName': file_result['file_name'],
                        'error': str(e)
                    })
            
            # 提交所有文档
            db.session.commit()
            
            current_app.logger.info(
                f"[KB:upload_zip] created {len(created_docs)} documents, "
                f"{len(failed_files)} failed"
            )
            
            # 如果状态为 published，批量向量化
            if status == 'published' and created_docs:
                vector_manager = get_vector_manager()
                vectorized_count = 0
                
                for doc in created_docs:
                    try:
                        success = vector_manager.process_document(doc, kb)
                        if success:
                            vectorized_count += 1
                    except Exception as ve:
                        current_app.logger.error(
                            f"[KB:upload_zip] vectorization failed for doc_id={doc.id}: {ve}"
                        )
                
                db.session.commit()
                current_app.logger.info(
                    f"[KB:upload_zip] vectorized {vectorized_count}/{len(created_docs)} documents"
                )
            
            return success_response(
                {
                    'message': f'批量上传完成：成功 {len(created_docs)} 个，失败 {len(failed_files)} 个',
                    'documents': [doc.to_dict() for doc in created_docs],
                    'failedFiles': failed_files,
                    'summary': {
                        'total': len(file_results),
                        'success': len(created_docs),
                        'failed': len(failed_files)
                    }
                },
                status_code=201
            )
            
        finally:
            # 清理临时文件
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                    current_app.logger.info(f"[KB:upload_zip] cleaned up temp file: {zip_path}")
                except Exception as e:
                    current_app.logger.warning(f"[KB:upload_zip] failed to clean up temp file: {e}")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:upload_zip] error: {e}")
        return error_response(f'ZIP 文件上传失败: {str(e)}', status_code=500)


# ==================== 批量操作接口 ====================

@kb_bp.route('/<string:kb_id>/documents/batch', methods=['POST'])
@login_required
def batch_operations(kb_id):
    """批量操作文档"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        data = request.get_json()
        
        # 验证必需字段
        is_valid, missing_fields = validate_required_fields(data, ['operation', 'documentIds'])
        if not is_valid:
            return error_response(
                f'缺少必需字段: {", ".join(missing_fields)}',
                status_code=400
            )
        
        operation = data.get('operation')
        document_ids = data.get('documentIds', [])
        
        if not isinstance(document_ids, list) or len(document_ids) == 0:
            return error_response('documentIds 必须是非空数组', status_code=400)
        
        current_app.logger.info(
            f"[KB:batch_operations] kb_id={kb_id}, operation='{operation}', "
            f"document_count={len(document_ids)}"
        )
        
        # 获取所有文档
        documents = Document.query.filter(
            Document.id.in_(document_ids),
            Document.kb_id == kb_id
        ).all()
        
        if len(documents) != len(document_ids):
            found_ids = [doc.id for doc in documents]
            missing_ids = [doc_id for doc_id in document_ids if doc_id not in found_ids]
            return error_response(
                f'部分文档不存在: {", ".join(missing_ids)}',
                status_code=404
            )
        
        success_count = 0
        failed_count = 0
        errors = []
        
        # 执行批量操作
        if operation == 'delete':
            # 批量删除
            vector_manager = get_vector_manager()
            
            for doc in documents:
                try:
                    # 删除向量
                    vector_manager.delete_document_vectors(doc.id)
                    
                    # 删除文档
                    db.session.delete(doc)
                    success_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': str(e)
                    })
                    current_app.logger.error(f"[KB:batch_operations] delete failed for doc_id={doc.id}: {e}")
            
            db.session.commit()
            message = f'批量删除完成：成功 {success_count} 个，失败 {failed_count} 个'
            
        elif operation == 'publish':
            # 批量发布
            vector_manager = get_vector_manager()
            
            for doc in documents:
                try:
                    old_status = doc.status
                    doc.status = 'published'
                    doc.updated_at = datetime.utcnow()
                    
                    # 如果之前不是 published 状态，触发向量化
                    if old_status != 'published':
                        vector_manager.process_document(doc, kb)
                    
                    success_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': str(e)
                    })
                    current_app.logger.error(f"[KB:batch_operations] publish failed for doc_id={doc.id}: {e}")
            
            db.session.commit()
            message = f'批量发布完成：成功 {success_count} 个，失败 {failed_count} 个'
            
        elif operation == 'draft':
            # 批量转为草稿
            for doc in documents:
                try:
                    doc.status = 'draft'
                    doc.updated_at = datetime.utcnow()
                    success_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': str(e)
                    })
                    current_app.logger.error(f"[KB:batch_operations] draft failed for doc_id={doc.id}: {e}")
            
            db.session.commit()
            message = f'批量转为草稿完成：成功 {success_count} 个，失败 {failed_count} 个'
            
        elif operation == 'sync-vectors':
            # 批量同步向量
            vector_manager = get_vector_manager()
            
            for doc in documents:
                try:
                    # 只处理已发布的文档
                    if doc.status == 'published':
                        vector_manager.process_document(doc, kb)
                        success_count += 1
                    else:
                        failed_count += 1
                        errors.append({
                            'documentId': doc.id,
                            'title': doc.title,
                            'error': '文档未发布，跳过向量化'
                        })
                    
                except Exception as e:
                    failed_count += 1
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': str(e)
                    })
                    current_app.logger.error(f"[KB:batch_operations] sync-vectors failed for doc_id={doc.id}: {e}")
            
            db.session.commit()
            message = f'批量向量同步完成：成功 {success_count} 个，失败 {failed_count} 个'
            
        else:
            return error_response(
                f'不支持的操作: {operation}。支持的操作: delete, publish, draft, sync-vectors',
                status_code=400
            )
        
        current_app.logger.info(
            f"[KB:batch_operations] operation='{operation}' completed: "
            f"success={success_count}, failed={failed_count}"
        )
        
        return success_response({
            'message': message,
            'summary': {
                'total': len(document_ids),
                'success': success_count,
                'failed': failed_count
            },
            'errors': errors if errors else None
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:batch_operations] error: {e}")
        return error_response(f'批量操作失败: {str(e)}', status_code=500)


# ==================== 向量化接口 ====================

@kb_bp.route('/<string:kb_id>/documents/<string:doc_id>/vectorize', methods=['POST'])
@login_required
def vectorize_document(kb_id, doc_id):
    """向量化单个文档"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取文档
        doc = db.session.get(Document, doc_id)
        if not doc or doc.kb_id != kb_id:
            return error_response('文档不存在', status_code=404)
        
        current_app.logger.info(
            f"[KB:vectorize_document] kb_id={kb_id}, doc_id={doc_id}, "
            f"title='{doc.title}', status='{doc.status}'"
        )
        
        # 检查文档状态
        if doc.status != 'published':
            return error_response(
                '只能向量化已发布的文档',
                status_code=400
            )
        
        # 检查文档内容
        if not doc.content or not doc.content.strip():
            return error_response(
                '文档内容为空，无法向量化',
                status_code=400
            )
        
        # 获取可选参数
        data = request.get_json() or {}
        force = data.get('force', False)  # 是否强制重新向量化
        chunk_size = data.get('chunkSize')
        chunk_overlap = data.get('chunkOverlap')
        
        # 如果未提供chunk_size和chunk_overlap，从知识库设置中获取默认值
        if chunk_size is None or chunk_overlap is None:
            try:
                from models.settings import KnowledgeBaseSettings
                kb_settings = KnowledgeBaseSettings.query.first()
                
                if chunk_size is None and kb_settings and kb_settings.chunk_size:
                    chunk_size = kb_settings.chunk_size
                    
                if chunk_overlap is None and kb_settings and kb_settings.chunk_overlap:
                    chunk_overlap = kb_settings.chunk_overlap
                    
                current_app.logger.info(
                    f"[KB:vectorize_document] Using settings from database: "
                    f"chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
                )
            except Exception as e:
                current_app.logger.warning(
                    f"[KB:vectorize_document] Failed to get settings from database: {e}"
                )
        
        # 如果不是强制模式，检查是否已经向量化
        if not force and doc.vector_status == 'completed' and doc.chunk_count > 0:
            current_app.logger.info(
                f"[KB:vectorize_document] doc_id={doc_id} already vectorized, skipping"
            )
            return success_response({
                'message': '文档已经向量化，如需重新向量化请设置 force=true',
                'document': doc.to_dict()
            })
        
        # 执行向量化
        try:
            vector_manager = get_vector_manager()
            
            # 更新状态为处理中
            doc.vector_status = 'processing'
            doc.vector_error = None
            db.session.commit()
            
            # 处理文档
            success = vector_manager.process_document(
                doc, kb,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            db.session.commit()
            
            if success:
                current_app.logger.info(
                    f"[KB:vectorize_document] successfully vectorized doc_id={doc_id}, "
                    f"chunks={doc.chunk_count}"
                )
                return success_response({
                    'message': f'文档向量化成功，生成 {doc.chunk_count} 个文本块',
                    'document': doc.to_dict()
                })
            else:
                current_app.logger.warning(
                    f"[KB:vectorize_document] vectorization failed for doc_id={doc_id}: "
                    f"{doc.vector_error}"
                )
                return error_response(
                    f'文档向量化失败: {doc.vector_error or "未知错误"}',
                    status_code=500
                )
                
        except Exception as ve:
            current_app.logger.exception(f"[KB:vectorize_document] error: {ve}")
            doc.vector_status = 'failed'
            doc.vector_error = str(ve)
            db.session.commit()
            return error_response(
                f'文档向量化失败: {str(ve)}',
                status_code=500
            )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:vectorize_document] error: {e}")
        return error_response(f'向量化请求失败: {str(e)}', status_code=500)


@kb_bp.route('/<string:kb_id>/sync-vectors', methods=['POST'])
@login_required
def sync_vectors(kb_id):
    """批量同步知识库向量"""
    import time
    start_time = time.time()
    
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取参数
        data = request.get_json() or {}
        force = data.get('force', False)  # 是否强制重新同步所有文档
        document_ids = data.get('documentIds', [])  # 可选：指定要同步的文档ID列表
        chunk_size = data.get('chunkSize')
        chunk_overlap = data.get('chunkOverlap')
        
        # 如果未提供chunk_size和chunk_overlap，从知识库设置中获取默认值
        if chunk_size is None or chunk_overlap is None:
            try:
                from models.settings import KnowledgeBaseSettings
                kb_settings = KnowledgeBaseSettings.query.first()
                
                if chunk_size is None and kb_settings and kb_settings.chunk_size:
                    chunk_size = kb_settings.chunk_size
                    
                if chunk_overlap is None and kb_settings and kb_settings.chunk_overlap:
                    chunk_overlap = kb_settings.chunk_overlap
                    
                current_app.logger.info(
                    f"[KB:sync_vectors] Using settings from database: "
                    f"chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
                )
            except Exception as e:
                current_app.logger.warning(
                    f"[KB:sync_vectors] Failed to get settings from database: {e}"
                )
        
        current_app.logger.info(
            f"[KB:sync_vectors] Starting vectorization - kb_id={kb_id}, force={force}, "
            f"document_ids={document_ids if document_ids else 'all'}, "
            f"chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
        )
        
        # 构建查询
        query = Document.query.filter(
            Document.kb_id == kb_id,
            Document.status == 'published'
        )
        
        # 如果指定了文档ID列表
        if document_ids:
            if not isinstance(document_ids, list):
                return error_response('documentIds 必须是数组', status_code=400)
            query = query.filter(Document.id.in_(document_ids))
        
        # 如果不是强制模式，只同步未完成的文档
        if not force:
            query = query.filter(
                db.or_(
                    Document.vector_status == 'pending',
                    Document.vector_status == 'failed',
                    Document.chunk_count == 0
                )
            )
        
        # 获取需要同步的文档
        documents = query.all()
        
        if not documents:
            duration = round(time.time() - start_time, 2)
            message = '没有需要同步的文档'
            if not force:
                message += '（所有文档已完成向量化，如需重新同步请设置 force=true）'
            
            current_app.logger.info(
                f"[KB:sync_vectors] {message} - duration={duration}s"
            )
            return success_response({
                'message': message,
                'summary': {
                    'total': 0,
                    'success': 0,
                    'failed': 0,
                    'skipped': 0
                },
                'errors': [],
                'duration': duration
            })
        
        current_app.logger.info(
            f"[KB:sync_vectors] Found {len(documents)} documents to sync"
        )
        
        # 批量处理文档
        vector_manager = get_vector_manager()
        success_count = 0
        failed_count = 0
        skipped_count = 0
        errors = []
        
        current_app.logger.info(
            f"[KB:sync_vectors] Starting to process {len(documents)} documents"
        )
        
        for idx, doc in enumerate(documents, 1):
            doc_start_time = time.time()
            try:
                current_app.logger.info(
                    f"[KB:sync_vectors] Processing document {idx}/{len(documents)}: "
                    f"doc_id={doc.id}, title='{doc.title}'"
                )
                
                # 检查文档内容
                if not doc.content or not doc.content.strip():
                    skipped_count += 1
                    error_detail = '文档内容为空，无法进行向量化'
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': error_detail
                    })
                    current_app.logger.warning(
                        f"[KB:sync_vectors] Skipped document {idx}/{len(documents)}: "
                        f"doc_id={doc.id} - {error_detail}"
                    )
                    continue
                
                # 更新状态为处理中
                doc.vector_status = 'processing'
                doc.vector_error = None
                db.session.commit()
                
                current_app.logger.debug(
                    f"[KB:sync_vectors] Vectorizing doc_id={doc.id} with "
                    f"chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
                )
                
                # 处理文档
                success = vector_manager.process_document(
                    doc, kb,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )
                
                doc_duration = round(time.time() - doc_start_time, 2)
                
                if success:
                    success_count += 1
                    current_app.logger.info(
                        f"[KB:sync_vectors] Successfully vectorized document {idx}/{len(documents)}: "
                        f"doc_id={doc.id}, chunks={doc.chunk_count}, duration={doc_duration}s"
                    )
                else:
                    failed_count += 1
                    error_detail = doc.vector_error or '向量化处理失败，未生成向量数据'
                    errors.append({
                        'documentId': doc.id,
                        'title': doc.title,
                        'error': error_detail
                    })
                    current_app.logger.warning(
                        f"[KB:sync_vectors] Failed to vectorize document {idx}/{len(documents)}: "
                        f"doc_id={doc.id} - {error_detail}, duration={doc_duration}s"
                    )
                
            except Exception as e:
                failed_count += 1
                doc_duration = round(time.time() - doc_start_time, 2)
                
                # 生成更详细的错误消息
                error_msg = str(e)
                if 'embedding' in error_msg.lower():
                    error_detail = f'嵌入生成失败: {error_msg}'
                elif 'database' in error_msg.lower() or 'sql' in error_msg.lower():
                    error_detail = f'数据库操作失败: {error_msg}'
                elif 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                    error_detail = f'网络连接失败: {error_msg}'
                else:
                    error_detail = f'处理异常: {error_msg}'
                
                errors.append({
                    'documentId': doc.id,
                    'title': doc.title,
                    'error': error_detail
                })
                
                # 更新文档状态
                doc.vector_status = 'failed'
                doc.vector_error = error_detail
                
                current_app.logger.error(
                    f"[KB:sync_vectors] Exception processing document {idx}/{len(documents)}: "
                    f"doc_id={doc.id} - {error_detail}, duration={doc_duration}s",
                    exc_info=True
                )
        
        # 提交所有更改
        db.session.commit()
        
        # 计算总耗时
        duration = round(time.time() - start_time, 2)
        
        total = len(documents)
        message = f'向量同步完成：成功 {success_count} 个，失败 {failed_count} 个'
        if skipped_count > 0:
            message += f'，跳过 {skipped_count} 个'
        
        current_app.logger.info(
            f"[KB:sync_vectors] Vectorization completed - total={total}, "
            f"success={success_count}, failed={failed_count}, skipped={skipped_count}, "
            f"duration={duration}s, avg_time_per_doc={round(duration/total, 2)}s"
        )
        
        # 如果有错误，记录详细的错误摘要
        if errors:
            current_app.logger.warning(
                f"[KB:sync_vectors] Errors encountered during vectorization:"
            )
            for error in errors:
                current_app.logger.warning(
                    f"  - doc_id={error['documentId']}, title='{error['title']}': {error['error']}"
                )
        
        return success_response({
            'message': message,
            'summary': {
                'total': total,
                'success': success_count,
                'failed': failed_count,
                'skipped': skipped_count
            },
            'errors': errors,
            'duration': duration
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"[KB:sync_vectors] error: {e}")
        return error_response(f'向量同步失败: {str(e)}', status_code=500)


# ==================== 搜索接口 ====================

@kb_bp.route('/<string:kb_id>/search', methods=['POST'])
@login_required
def search_in_kb(kb_id):
    """在知识库内搜索文档"""
    try:
        # 验证知识库是否存在
        kb = db.session.get(KnowledgeBase, kb_id)
        if not kb:
            return error_response('知识库不存在', status_code=404)
        
        # 获取搜索参数
        data = request.get_json()
        
        # 验证必需字段
        is_valid, missing_fields = validate_required_fields(data, ['query'])
        if not is_valid:
            return error_response(
                f'缺少必需字段: {", ".join(missing_fields)}',
                status_code=400
            )
        
        query = data.get('query', '').strip()
        if not query:
            return error_response('搜索关键词不能为空', status_code=400)
        
        # 获取知识库设置，使用max_search_results作为默认limit
        try:
            from models.settings import KnowledgeBaseSettings
            kb_settings = KnowledgeBaseSettings.query.first()
            default_limit = kb_settings.max_search_results if kb_settings else 10
        except Exception as e:
            current_app.logger.warning(f"Failed to get KB settings: {e}")
            default_limit = 10
        
        # 获取可选参数
        limit = data.get('limit', default_limit)
        search_type = data.get('searchType', 'hybrid')  # vector, sql, hybrid
        similarity_threshold = data.get('similarityThreshold', kb_settings.similarity_threshold if kb_settings else 0.7)
        highlight = data.get('highlight', True)  # 是否高亮显示
        
        current_app.logger.info(
            f"[KB:search_in_kb] kb_id={kb_id}, query='{query}', "
            f"limit={limit}, search_type='{search_type}'"
        )
        
        # 执行搜索
        vector_manager = get_vector_manager()
        results = []
        
        if search_type == 'vector':
            # 纯向量搜索
            results = vector_manager.search_similar(
                query=query,
                kb_id=kb_id,
                limit=limit,
                similarity_threshold=similarity_threshold
            )
        elif search_type == 'sql':
            # 纯 SQL 全文搜索
            search_pattern = f"%{query}%"
            sql_query = Document.query.filter(
                Document.kb_id == kb_id,
                Document.status == 'published',
                db.or_(
                    Document.title.like(search_pattern),
                    Document.content.like(search_pattern)
                )
            ).limit(limit).all()
            
            results = []
            for doc in sql_query:
                results.append({
                    'document_id': doc.id,
                    'kb_id': doc.kb_id,
                    'title': doc.title,
                    'content': doc.content[:500],  # 截取前500字符
                    'category': doc.category,
                    'author': doc.author,
                    'similarity': 0.5,  # SQL 搜索给予固定相似度
                    'search_type': 'sql'
                })
        else:
            # 混合搜索（默认）
            results = vector_manager.hybrid_search(
                query=query,
                kb_id=kb_id,
                limit=limit,
                similarity_threshold=similarity_threshold
            )
        
        # 添加高亮
        if highlight and results:
            results = _highlight_search_results(results, query)
        
        # 获取完整的文档信息
        enriched_results = []
        for result in results:
            doc_id = result.get('document_id')
            doc = db.session.get(Document, doc_id)
            
            if doc:
                enriched_result = {
                    'document': doc.to_dict(),
                    'similarity': result.get('similarity', 0),
                    'searchType': result.get('search_type', 'unknown'),
                    'matchedContent': result.get('content', ''),
                    'highlightedContent': result.get('highlighted_content', result.get('content', ''))
                }
                
                # 添加向量块信息
                if 'chunk_index' in result:
                    enriched_result['chunkIndex'] = result['chunk_index']
                
                # 注意：我们不再需要total_chunks，因为现在返回的是单个文本块而不是聚合结果
                
                if 'matched_chunks' in result:
                    enriched_result['matchedChunks'] = result['matched_chunks']
                
                enriched_results.append(enriched_result)
        
        current_app.logger.info(
            f"[KB:search_in_kb] found {len(enriched_results)} results for query '{query}'"
        )
        
        return success_response({
            'results': enriched_results,
            'query': query,
            'total': len(enriched_results),
            'searchType': search_type
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:search_in_kb] error: {e}")
        return error_response(f'搜索失败: {str(e)}', status_code=500)


@kb_bp.route('/search', methods=['POST'])
@login_required
def search_all_kbs():
    """跨知识库搜索文档"""
    try:
        # 获取搜索参数
        data = request.get_json()
        
        # 验证必需字段
        is_valid, missing_fields = validate_required_fields(data, ['query'])
        if not is_valid:
            return error_response(
                f'缺少必需字段: {", ".join(missing_fields)}',
                status_code=400
            )
        
        query = data.get('query', '').strip()
        if not query:
            return error_response('搜索关键词不能为空', status_code=400)
        
        # 获取知识库设置，使用max_search_results作为默认limit
        try:
            from models.settings import KnowledgeBaseSettings
            kb_settings = KnowledgeBaseSettings.query.first()
            default_limit = kb_settings.max_search_results if kb_settings else 10
        except Exception as e:
            current_app.logger.warning(f"Failed to get KB settings: {e}")
            default_limit = 10
        
        # 获取可选参数
        limit = data.get('limit', default_limit)
        search_type = data.get('searchType', 'hybrid')  # vector, sql, hybrid
        similarity_threshold = data.get('similarityThreshold', kb_settings.similarity_threshold if kb_settings else 0.7)
        highlight = data.get('highlight', True)
        kb_ids = data.get('kbIds', [])  # 可选：限制搜索的知识库ID列表
        
        current_app.logger.info(
            f"[KB:search_all_kbs] query='{query}', limit={limit}, "
            f"search_type='{search_type}', kb_ids={kb_ids if kb_ids else 'all'}"
        )
        
        # 如果指定了知识库列表，验证它们是否存在
        if kb_ids:
            if not isinstance(kb_ids, list):
                return error_response('kbIds 必须是数组', status_code=400)
            
            # 验证知识库是否存在
            existing_kbs = KnowledgeBase.query.filter(
                KnowledgeBase.id.in_(kb_ids)
            ).all()
            
            if len(existing_kbs) != len(kb_ids):
                existing_ids = [kb.id for kb in existing_kbs]
                missing_ids = [kb_id for kb_id in kb_ids if kb_id not in existing_ids]
                return error_response(
                    f'部分知识库不存在: {", ".join(missing_ids)}',
                    status_code=404
                )
        
        # 执行搜索
        vector_manager = get_vector_manager()
        all_results = []
        
        if search_type == 'vector':
            # 纯向量搜索
            # 如果指定了知识库列表，分别搜索每个知识库
            if kb_ids:
                for kb_id in kb_ids:
                    kb_results = vector_manager.search_similar(
                        query=query,
                        kb_id=kb_id,
                        limit=limit,
                        similarity_threshold=similarity_threshold
                    )
                    all_results.extend(kb_results)
            else:
                # 搜索所有知识库
                all_results = vector_manager.search_similar(
                    query=query,
                    kb_id=None,
                    limit=limit * 2,  # 获取更多结果用于排序
                    similarity_threshold=similarity_threshold
                )
        elif search_type == 'sql':
            # 纯 SQL 全文搜索
            search_pattern = f"%{query}%"
            sql_query = Document.query.filter(
                Document.status == 'published',
                db.or_(
                    Document.title.like(search_pattern),
                    Document.content.like(search_pattern)
                )
            )
            
            # 如果指定了知识库列表
            if kb_ids:
                sql_query = sql_query.filter(Document.kb_id.in_(kb_ids))
            
            sql_docs = sql_query.limit(limit).all()
            
            for doc in sql_docs:
                all_results.append({
                    'document_id': doc.id,
                    'kb_id': doc.kb_id,
                    'title': doc.title,
                    'content': doc.content[:500],
                    'category': doc.category,
                    'author': doc.author,
                    'similarity': 0.5,
                    'search_type': 'sql'
                })
        else:
            # 混合搜索（默认）
            if kb_ids:
                for kb_id in kb_ids:
                    kb_results = vector_manager.hybrid_search(
                        query=query,
                        kb_id=kb_id,
                        limit=limit,
                        similarity_threshold=similarity_threshold
                    )
                    all_results.extend(kb_results)
            else:
                all_results = vector_manager.hybrid_search(
                    query=query,
                    kb_id=None,
                    limit=limit * 2,
                    similarity_threshold=similarity_threshold
                )
        
        # 按相似度排序并限制结果数量
        all_results.sort(key=lambda x: x.get('similarity', 0), reverse=True)
        all_results = all_results[:limit]
        
        # 添加高亮
        if highlight and all_results:
            all_results = _highlight_search_results(all_results, query)
        
        # 获取完整的文档和知识库信息
        enriched_results = []
        for result in all_results:
            doc_id = result.get('document_id')
            kb_id = result.get('kb_id')
            
            doc = db.session.get(Document, doc_id)
            kb = db.session.get(KnowledgeBase, kb_id)
            
            if doc and kb:
                enriched_result = {
                    'document': doc.to_dict(),
                    'knowledgeBase': {
                        'id': kb.id,
                        'name': kb.name,
                        'description': kb.description
                    },
                    'similarity': result.get('similarity', 0),
                    'searchType': result.get('search_type', 'unknown'),
                    'matchedContent': result.get('content', ''),
                    'highlightedContent': result.get('highlighted_content', result.get('content', ''))
                }
                
                # 添加向量块信息
                if 'chunk_index' in result:
                    enriched_result['chunkIndex'] = result['chunk_index']
                
                if 'total_chunks' in result:
                    enriched_result['totalChunks'] = result['total_chunks']
                
                if 'matched_chunks' in result:
                    enriched_result['matchedChunks'] = result['matched_chunks']
                
                enriched_results.append(enriched_result)
        
        current_app.logger.info(
            f"[KB:search_all_kbs] found {len(enriched_results)} results for query '{query}'"
        )
        
        return success_response({
            'results': enriched_results,
            'query': query,
            'total': len(enriched_results),
            'searchType': search_type
        })
        
    except Exception as e:
        current_app.logger.exception(f"[KB:search_all_kbs] error: {e}")
        return error_response(f'搜索失败: {str(e)}', status_code=500)


def _highlight_search_results(results: list, query: str) -> list:
    """
    为搜索结果添加高亮标记
    
    Args:
        results: 搜索结果列表
        query: 搜索关键词
        
    Returns:
        添加了高亮的结果列表
    """
    try:
        import re
        
        # 分词（简单按空格分割）
        keywords = query.split()
        
        for result in results:
            content = result.get('content', '')
            if not content:
                continue
            
            # 为每个关键词添加高亮标记
            highlighted = content
            for keyword in keywords:
                if not keyword.strip():
                    continue
                
                # 使用正则表达式进行不区分大小写的替换
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                highlighted = pattern.sub(
                    lambda m: f'<mark>{m.group(0)}</mark>',
                    highlighted
                )
            
            result['highlighted_content'] = highlighted
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to highlight search results: {e}")
        return results
