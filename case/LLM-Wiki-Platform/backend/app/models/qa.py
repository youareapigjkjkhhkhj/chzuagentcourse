# 问答模型
from datetime import datetime
from app import db

class QARecord(db.Model):
    """问答记录模型"""
    __tablename__ = 'qa_records'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    document_ids = db.Column(db.JSON)
    confidence = db.Column(db.Numeric(3, 2))
    feedback = db.Column(db.Enum('helpful', 'not_helpful', 'neutral'))
    feedback_comment = db.Column(db.Text)
    response_time = db.Column(db.Integer)  # 毫秒
    model_used = db.Column(db.String(50))
    tokens_used = db.Column(db.Integer)
    session_id = db.Column(db.String(100))
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'question': self.question,
            'answer': self.answer,
            'document_ids': self.document_ids,
            'confidence': float(self.confidence) if self.confidence else None,
            'feedback': self.feedback,
            'feedback_comment': self.feedback_comment,
            'response_time': self.response_time,
            'model_used': self.model_used,
            'tokens_used': self.tokens_used,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<QARecord {self.id}>'

class AuditLog(db.Model):
    """审计日志模型"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(50), nullable=False)
    resource = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Integer)
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    request_method = db.Column(db.String(10))
    request_path = db.Column(db.String(500))
    response_status = db.Column(db.Integer)
    execution_time = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'resource': self.resource,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<AuditLog {self.action} {self.resource}>'