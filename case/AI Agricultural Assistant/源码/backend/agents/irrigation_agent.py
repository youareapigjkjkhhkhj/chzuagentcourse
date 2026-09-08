from backend.services.text_service import query_groq_text
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.prompt_loader import get_prompt


class IrrigationAgent(AgriAgentBase):
    """
    IrrigationAgent:
    Handles irrigation and water management questions ONLY.
    """

    name = "IrrigationAgent"

    def handle_query(
        self,
        query: str = None,
        image_path: str = None,
        chat_history: str = None,
        request_id: str = None,
        session_id: str = None,
        **kwargs,
    ) -> str:

        if not query or not isinstance(query, str) or not query.strip():
            response = (
                "Please ask an irrigation-related question.\n"
                "Examples:\n"
                "• How often should I irrigate tomatoes?\n"
                "• How to save water using drip irrigation?\n"
                "• How should irrigation change during summer?"
            )
            return self.respond_and_record("", response, image_path)

        clean_query = query.strip()

        try:
            prompt = get_prompt(
                "irrigation_agent.template",
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
            resp = "Irrigation advice could not be generated at this time."

        return self.respond_and_record(
            query=clean_query,
            response=resp,
            image_path=image_path,
        )
