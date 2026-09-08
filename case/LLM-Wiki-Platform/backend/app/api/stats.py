# 统计API
from flask import jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from app import db
from app.models.document import Document
from app.models.user import User
from app.models.qa import QARecord

def register_routes(bp):
    """注册统计路由"""

    @bp.route('/stats', methods=['GET'])
    @jwt_required()
    def get_stats():
        """获取平台聚合统计（文档数/浏览量/问答数/活跃用户）"""
        doc_count = db.session.query(func.count(Document.id))\
            .filter(Document.deleted_at.is_(None)).scalar() or 0
        total_views = db.session.query(func.coalesce(func.sum(Document.view_count), 0))\
            .filter(Document.deleted_at.is_(None)).scalar() or 0
        qa_count = db.session.query(func.count(QARecord.id)).scalar() or 0
        active_users = db.session.query(func.count(User.id))\
            .filter(User.status == 'active', User.deleted_at.is_(None)).scalar() or 0

        return jsonify({
            'document_count': int(doc_count),
            'total_views': int(total_views),
            'qa_count': int(qa_count),
            'active_users': int(active_users)
        })