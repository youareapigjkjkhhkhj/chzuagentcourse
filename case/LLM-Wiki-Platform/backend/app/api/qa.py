# 问答API
import json
from flask import request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.qa_service import QAService
from app.services.ai_service import AIService

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
    
    @bp.route('/qa/ask_stream', methods=['POST'])
    @jwt_required()
    def ask_question_stream():
        """提问（流式输出 SSE）"""
        data = request.get_json()
        question = data.get('question')
        context = data.get('context', {})
        session_id = data.get('session_id')
        
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        
        user_id = get_jwt_identity()
        ip_address = request.remote_addr
        
        # 1. 先搜索知识库
        search_results = AIService.search_similar_documents(question, top_k=5)
        doc_context = AIService.build_context(search_results)
        
        # 2. 准备来源数据（先发出去）
        sources_data = json.dumps({
            'type': 'sources',
            'sources': search_results
        }, ensure_ascii=False, default=str)
        
        # 3. 流式生成回答
        def generate():
            yield f"data: {sources_data}\n\n"
            try:
                full_answer = ""
                for chunk in AIService.generate_answer_stream(question, doc_context):
                    full_answer += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                
                # 4. 保存记录
                import time
                start_ts = data.get('_start_ts', time.time())
                response_time = int((time.time() - start_ts) * 1000)
                if response_time > 2147483647:
                    response_time = 2147483647
                from app.models.qa import QARecord
                from app import db
                record = QARecord(
                    user_id=user_id,
                    question=question,
                    answer=full_answer,
                    document_ids=[r['document_id'] for r in search_results],
                    confidence=0.85,
                    response_time=response_time,
                    model_used='gpt-5-mini',
                    tokens_used=0,
                    session_id=session_id,
                    ip_address=ip_address
                )
                db.session.add(record)
                db.session.commit()
                
                yield f"data: {json.dumps({'type': 'done', 'record_id': record.id}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )
    
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