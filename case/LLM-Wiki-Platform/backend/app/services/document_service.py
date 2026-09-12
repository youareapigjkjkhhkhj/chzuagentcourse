# 文档服务
from datetime import datetime
from app import db
from app.models.document import Document, Category, Tag, DocumentVersion
from app.services.ai_service import AIService

class DocumentService:
    """文档服务"""
    
    @staticmethod
    def get_documents(page=1, per_page=20, category_id=None, keyword=None, status=None):
        """获取文档列表"""
        query = Document.query.filter(Document.deleted_at.is_(None))
        
        if status:
            query = query.filter(Document.status == status)
        
        if category_id:
            query = query.filter(Document.category_id == category_id)
        
        if keyword:
            query = query.filter(
                db.or_(
                    Document.title.ilike(f'%{keyword}%'),
                    Document.content.ilike(f'%{keyword}%')
                )
            )
        
        # 按置顶和创建时间排序
        query = query.order_by(Document.is_pinned.desc(), Document.created_at.desc())
        
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return {
            'items': [doc.to_dict() for doc in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        }
    
    @staticmethod
    def get_document_by_id(doc_id):
        """根据ID获取文档"""
        return Document.query.get(doc_id)
    
    @staticmethod
    def create_document(data, user_id):
        """创建文档"""
        try:
            # 验证分类是否存在
            if data.get('category_id'):
                category = Category.query.get(data['category_id'])
                if not category:
                    return None, 'Category not found'
            
            # 创建文档
            document = Document(
                title=data['title'],
                content=data.get('content', ''),
                summary=data.get('summary', ''),
                author_id=user_id,
                category_id=data.get('category_id'),
                status=data.get('status', 'draft'),
                visibility=data.get('visibility', 'public'),
                is_pinned=data.get('is_pinned', False),
                is_featured=data.get('is_featured', False),
                allow_comment=data.get('allow_comment', True)
            )
            
            # 处理标签
            if data.get('tag_ids'):
                tags = Tag.query.filter(Tag.id.in_(data['tag_ids'])).all()
                document.tags = tags
                for tag in tags:
                    tag.usage_count += 1
            
            db.session.add(document)
            db.session.flush()
            
            # 创建初始版本
            version = DocumentVersion(
                document_id=document.id,
                version=1,
                title=document.title,
                content=document.content,
                change_summary='Initial version',
                author_id=user_id
            )
            db.session.add(version)
            
            # 更新分类文档计数
            if document.category_id:
                category = Category.query.get(document.category_id)
                if category:
                    category.document_count += 1
            
            db.session.commit()
            
            # 向量化：已发布文档写入 Milvus 向量库（失败不影响主流程）
            if document.status == 'published' and document.content:
                AIService.process_document_for_embedding(document.id, document.content)
            
            return document, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def update_document(doc_id, data, user_id):
        """更新文档"""
        try:
            document = Document.query.get(doc_id)
            if not document:
                return None, 'Document not found'
            
            # 保存旧版本
            old_version = DocumentVersion(
                document_id=document.id,
                version=document.version,
                title=document.title,
                content=document.content,
                change_summary=data.get('change_summary', 'Updated'),
                author_id=user_id
            )
            db.session.add(old_version)
            
            # 更新文档
            if 'title' in data:
                document.title = data['title']
            if 'content' in data:
                document.content = data['content']
            if 'summary' in data:
                document.summary = data['summary']
            if 'category_id' in data:
                document.category_id = data['category_id']
            if 'status' in data:
                document.status = data['status']
                if data['status'] == 'published' and not document.published_at:
                    document.published_at = datetime.utcnow()
            if 'visibility' in data:
                document.visibility = data['visibility']
            if 'is_pinned' in data:
                document.is_pinned = data['is_pinned']
            if 'is_featured' in data:
                document.is_featured = data['is_featured']
            if 'allow_comment' in data:
                document.allow_comment = data['allow_comment']
            
            # 更新版本号
            document.version += 1
            
            # 更新标签
            if 'tag_ids' in data:
                # 减少旧标签计数
                for tag in document.tags:
                    tag.usage_count = max(0, tag.usage_count - 1)
                
                # 添加新标签
                tags = Tag.query.filter(Tag.id.in_(data['tag_ids'])).all()
                document.tags = tags
                for tag in tags:
                    tag.usage_count += 1
            
            db.session.commit()
            
            # 向量化：先清除旧向量，再写入新内容（失败不影响主流程）
            if document.status == 'published' and document.content:
                AIService.remove_document_embeddings(document.id)
                AIService.process_document_for_embedding(document.id, document.content)
            
            return document, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def delete_document(doc_id, user_id):
        """删除文档（软删除）"""
        try:
            document = Document.query.get(doc_id)
            if not document:
                return False, 'Document not found'
            
            document.deleted_at = datetime.utcnow()
            document.status = 'archived'
            
            # 更新分类文档计数
            if document.category_id:
                category = Category.query.get(document.category_id)
                if category:
                    category.document_count = max(0, category.document_count - 1)
            
            db.session.commit()
            
            # 删除向量
            AIService.remove_document_embeddings(document.id)
            
            return True, None
        except Exception as e:
            db.session.rollback()
            return False, str(e)
    
    @staticmethod
    def toggle_document_status(doc_id, user_id):
        """切换文档发布状态"""
        try:
            document = Document.query.get(doc_id)
            if not document:
                return None, 'Document not found'
            
            if document.status == 'published':
                document.status = 'draft'
                document.published_at = None
            else:
                document.status = 'published'
                document.published_at = datetime.utcnow()
            
            db.session.commit()
            
            # 处理向量化
            if document.status == 'published' and document.content:
                AIService.process_document_for_embedding(document.id, document.content)
            else:
                AIService.remove_document_embeddings(document.id)
            
            return document, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def increment_view_count(doc_id):
        """增加查看次数"""
        document = Document.query.get(doc_id)
        if document:
            document.view_count += 1
            db.session.commit()
    
    @staticmethod
    def search_documents(keyword, category_id=None, tags=None):
        """搜索文档"""
        query = Document.query.filter(
            Document.status == 'published',
            Document.deleted_at.is_(None)
        )
        
        if keyword:
            query = query.filter(
                db.or_(
                    Document.title.ilike(f'%{keyword}%'),
                    Document.content.ilike(f'%{keyword}%')
                )
            )
        
        if category_id:
            query = query.filter(Document.category_id == category_id)
        
        if tags:
            query = query.filter(Document.tags.any(Tag.name.in_(tags)))
        
        documents = query.limit(50).all()
        
        return [doc.to_dict() for doc in documents]
    
    # 分类相关方法
    @staticmethod
    def get_categories():
        """获取分类列表"""
        categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
        return [cat.to_dict() for cat in categories]
    
    @staticmethod
    def get_category_by_id(category_id):
        """根据ID获取分类"""
        return Category.query.get(category_id)
    
    @staticmethod
    def create_category(data):
        """创建分类"""
        try:
            # 检查名称是否已存在
            existing = Category.query.filter_by(name=data['name'], parent_id=data.get('parent_id')).first()
            if existing:
                return None, 'Category name already exists in this level'
            
            category = Category(
                name=data['name'],
                description=data.get('description'),
                parent_id=data.get('parent_id'),
                level=data.get('level', 1),
                sort_order=data.get('sort_order', 0),
                icon=data.get('icon'),
                color=data.get('color')
            )
            
            db.session.add(category)
            db.session.commit()
            
            return category, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def update_category(category_id, data):
        """更新分类"""
        try:
            category = Category.query.get(category_id)
            if not category:
                return None, 'Category not found'
            
            # 检查名称是否已存在
            if 'name' in data:
                existing = Category.query.filter(
                    Category.name == data['name'],
                    Category.parent_id == category.parent_id,
                    Category.id != category_id
                ).first()
                if existing:
                    return None, 'Category name already exists in this level'
                category.name = data['name']
            
            if 'description' in data:
                category.description = data['description']
            if 'sort_order' in data:
                category.sort_order = data['sort_order']
            if 'icon' in data:
                category.icon = data['icon']
            if 'color' in data:
                category.color = data['color']
            if 'is_active' in data:
                category.is_active = data['is_active']
            
            db.session.commit()
            
            return category, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def delete_category(category_id):
        """删除分类"""
        try:
            category = Category.query.get(category_id)
            if not category:
                return False, 'Category not found'
            
            # 检查是否有子分类
            if category.children:
                return False, 'Cannot delete category with children'
            
            # 检查是否有关联文档
            if category.document_count > 0:
                return False, 'Cannot delete category with documents'
            
            db.session.delete(category)
            db.session.commit()
            
            return True, None
        except Exception as e:
            db.session.rollback()
            return False, str(e)
    
    # 标签相关方法
    @staticmethod
    def get_tags():
        """获取标签列表"""
        tags = Tag.query.order_by(Tag.usage_count.desc()).all()
        return [tag.to_dict() for tag in tags]
    
    @staticmethod
    def get_tag_by_id(tag_id):
        """根据ID获取标签"""
        return Tag.query.get(tag_id)
    
    @staticmethod
    def create_tag(data):
        """创建标签"""
        try:
            # 检查名称是否已存在
            existing = Tag.query.filter_by(name=data['name']).first()
            if existing:
                return None, 'Tag name already exists'
            
            tag = Tag(
                name=data['name'],
                description=data.get('description'),
                color=data.get('color', '#409EFF')
            )
            
            db.session.add(tag)
            db.session.commit()
            
            return tag, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def update_tag(tag_id, data):
        """更新标签"""
        try:
            tag = Tag.query.get(tag_id)
            if not tag:
                return None, 'Tag not found'
            
            # 检查名称是否已存在
            if 'name' in data:
                existing = Tag.query.filter(Tag.name == data['name'], Tag.id != tag_id).first()
                if existing:
                    return None, 'Tag name already exists'
                tag.name = data['name']
            
            if 'description' in data:
                tag.description = data['description']
            if 'color' in data:
                tag.color = data['color']
            
            db.session.commit()
            
            return tag, None
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    
    @staticmethod
    def delete_tag(tag_id):
        """删除标签"""
        try:
            tag = Tag.query.get(tag_id)
            if not tag:
                return False, 'Tag not found'
            
            # 检查是否有关联文档
            if tag.usage_count > 0:
                return False, 'Cannot delete tag with documents'
            
            db.session.delete(tag)
            db.session.commit()
            
            return True, None
        except Exception as e:
            db.session.rollback()
            return False, str(e)