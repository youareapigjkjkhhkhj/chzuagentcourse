# 问答API
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.qa_service import QAService

def register_routes(bp):
    """注册问答路由"""
    
    @bp.route('/qa/ask', methods=['POST'])
    @jwt_required()
    def ask_question():
        """提问"""
        data = request.get_json()
        question = data.get('question')
        context = data.get('context', {})
        session_id = data.get('session_id')
        
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        
        user_id = get_jwt_identity()
        ip_address = request.remote_addr
        
        result = QAService.ask_question(
            question=question,
            user_id=user_id,
            context=context,
            session_id=session_id,
            ip_address=ip_address
        )
        
        return jsonify(result)
    
    @bp.route('/qa/history', methods=['GET'])
    @jwt_required()
    def get_qa_history():
        """获取问答历史"""
        user_id = get_jwt_identity()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        result = QAService.get_qa_history(user_id, page, per_page)
        
        return jsonify(result)
    
    @bp.route('/qa/feedback', methods=['POST'])
    @jwt_required()
    def submit_feedback():
        """提交反馈"""
        data = request.get_json()
        record_id = data.get('record_id')
        feedback = data.get('feedback')
        comment = data.get('comment')
        
        user_id = get_jwt_identity()
        
        success, error = QAService.submit_feedback(record_id, feedback, comment, user_id)
        if error:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': 'Feedback submitted successfully'})