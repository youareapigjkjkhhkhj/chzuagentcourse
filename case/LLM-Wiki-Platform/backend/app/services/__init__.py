# 服务层初始化
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.qa_service import QAService
from app.services.ai_service import AIService

__all__ = [
    'AuthService',
    'DocumentService',
    'QAService',
    'AIService'
]