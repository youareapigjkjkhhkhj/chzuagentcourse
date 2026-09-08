# 数据模型初始化
from app.models.user import User
from app.models.document import Document, Category, Tag, Comment, DocumentVersion, document_tags
from app.models.qa import QARecord, AuditLog

__all__ = [
    'User',
    'Document',
    'Category',
    'Tag',
    'Comment',
    'DocumentVersion',
    'document_tags',
    'QARecord',
    'AuditLog'
]