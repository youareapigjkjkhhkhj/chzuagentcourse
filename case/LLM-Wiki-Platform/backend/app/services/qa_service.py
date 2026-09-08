# 问答服务
import time
from datetime import datetime
from app import db
from app.models.qa import QARecord
from app.services.ai_service import AIService

class QAService:
    """问答服务"""
    
    @staticmethod
    def ask_question(question, user_id, context=None, session_id=None, ip_address=None):
        """提问并获取回答"""
        start_time = time.time()
        
        try:
            # 1. 向量搜索相关文档
            search_results = AIService.search_similar_documents(question, top_k=5)
            
            # 2. 构建上下文
            doc_context = AIService.build_context(search_results)
            
            # 3. 调用LLM生成回答
            answer_result = AIService.generate_answer(question, doc_context)
            
            # 4. 计算响应时间
            response_time = int((time.time() - start_time) * 1000)
            
            # 5. 保存问答记录
            record = QARecord(
                user_id=user_id,
                question=question,
                answer=answer_result['answer'],
                document_ids=[r['document_id'] for r in search_results],
                confidence=answer_result.get('confidence', 0.0),
                response_time=response_time,
                model_used=answer_result.get('model_used', 'gpt-5-mini'),
                tokens_used=answer_result.get('tokens_used', 0),
                session_id=session_id,
                ip_address=ip_address
            )
            db.session.add(record)
            db.session.commit()
            
            return {
                'answer': answer_result['answer'],
                'sources': search_results,
                'confidence': answer_result.get('confidence', 0.0),
                'response_time': response_time,
                'record_id': record.id
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def get_qa_history(user_id, page=1, per_page=20):
        """获取问答历史"""
        query = QARecord.query.filter_by(user_id=user_id).order_by(QARecord.created_at.desc())
        
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return {
            'items': [record.to_dict() for record in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        }
    
    @staticmethod
    def submit_feedback(record_id, feedback, comment, user_id):
        """提交反馈"""
        try:
            record = QARecord.query.get(record_id)
            if not record:
                return False, 'Record not found'
            
            if record.user_id != user_id:
                return False, 'Permission denied'
            
            record.feedback = feedback
            record.feedback_comment = comment
            
            db.session.commit()
            
            return True, None
        except Exception as e:
            db.session.rollback()
            return False, str(e)