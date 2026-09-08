"""REST API 路由：笔记管理 / 索引 / 问答。"""
from flask import Blueprint, request, jsonify, Response
from src.services import note_service, qa_service

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "notes-assistant"})


# ---------- 笔记管理 ----------
@api_bp.route("/notes", methods=["GET"])
def notes_list():
    return jsonify({"notes": note_service.list_notes()})


@api_bp.route("/notes/upload", methods=["POST"])
def notes_upload():
    if "file" not in request.files:
        return jsonify({"error": "缺少文件字段 file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    try:
        meta = note_service.save_note(f, f.filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"note": meta}), 201


@api_bp.route("/notes/<path:note_id>", methods=["GET"])
def notes_get(note_id):
    try:
        content = note_service.get_note_content(note_id)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"id": note_id, "content": content})


@api_bp.route("/notes/<path:note_id>", methods=["DELETE"])
def notes_delete(note_id):
    if not note_service.delete_note(note_id):
        return jsonify({"error": "笔记不存在"}), 404
    return jsonify({"deleted": note_id})


# ---------- 知识库索引 ----------
@api_bp.route("/index/rebuild", methods=["POST"])
def index_rebuild():
    try:
        result = note_service.build_index()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "built", **result})


@api_bp.route("/index/status", methods=["GET"])
def index_status():
    return jsonify(note_service.index_status())


# ---------- 问答 ----------
@api_bp.route("/qa", methods=["POST"])
def qa():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    try:
        result = qa_service.QAService().ask(question, top_k=data.get("top_k"))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(result)


@api_bp.route("/qa/stream", methods=["POST"])
def qa_stream():
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    return Response(
        qa_service.QAService().ask_stream(question, top_k=data.get("top_k")),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
