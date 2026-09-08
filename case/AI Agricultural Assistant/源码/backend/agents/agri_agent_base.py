from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from backend.services.history_service import log_interaction


class AgriAgentBase(ABC):
    name: str = "AgriAgentBase"

    @abstractmethod
    def handle_query(
        self,
        query: Optional[str] = None,
        image_path: Optional[str] = None,
        chat_history: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        pass


    @staticmethod
    def _normalize_query(q: Optional[str]) -> str:
        if q is None:
            return ""
        return q.strip()

    @staticmethod
    def _detect_query_type(query, image_path):
        normalized_query = AgriAgentBase._normalize_query(query)

        if normalized_query and image_path:
            return "multimodal"
        if image_path:
            return "image"
        return "text"

    def record(
        self,
        query,
        response,
        query_type,
        image_path=None,
        meta: Optional[dict] = None,   
    ):
        safe_response = str(response)

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": self.name,
            "query": query or "",
            "response": safe_response[:5000],
            "type": query_type,
        }

        if image_path:
            entry["image_path"] = image_path

        if meta:
            entry["meta"] = meta

        try:
            log_interaction(entry)
        except Exception:
            pass  


    def respond_and_record(
        self,
        query,
        response,
        image_path=None,
        meta: Optional[dict] = None,  
    ):
        query_type = self._detect_query_type(query, image_path)
        safe_response = str(response)

        self.record(
            query=query,
            response=safe_response,
            query_type=query_type,
            image_path=image_path,
            meta=meta,
        )

        return safe_response
