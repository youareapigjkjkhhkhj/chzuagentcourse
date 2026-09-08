from backend.services.text_service import query_groq_text
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.prompt_loader import get_prompt


class CropAgent(AgriAgentBase):
    """
    CropAgent:
    Handles general crop management questions.
    DOES NOT diagnose pests, diseases, or irrigation failures.
    """

    name = "CropAgent"

    def handle_query(
        self,
        query: str = None,
        image_path: str = None,
        chat_history: str = None,
        request_id: str = None,
        session_id: str = None,
        **kwargs,
    ) -> str:

        if not query or not query.strip():
            response = (
                "Please ask a crop management question.\n"
                "Examples:\n"
                "• What fertilizer should I use for tomatoes?\n"
                "• How should I prepare soil for rice?\n"
                "• What practices improve crop growth?"
            )
            return self.respond_and_record("", response, image_path)

        clean_query = query.strip()

        try:
            prompt = get_prompt(
                "crop_agent.template",
                chat_history=chat_history or "None",
                query=clean_query,
            )
        except Exception:
            prompt = f"PREVIOUS CONTEXT: {chat_history or 'None'}\nFARMER QUERY: {clean_query}"

        try:
            resp, _ = query_groq_text(
                prompt,
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            resp = "Crop advice could not be generated at this time."

        return self.respond_and_record(
            query=clean_query,
            response=resp,
            image_path=image_path,
        )
