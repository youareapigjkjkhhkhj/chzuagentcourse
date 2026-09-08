from backend.services.text_service import query_groq_text
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.prompt_loader import get_prompt


class YieldAgent(AgriAgentBase):
    """
    YieldAgent:
    Identifies reasons for low yield and provides
    high-level, conditional yield improvement guidance.
    """

    name = "YieldAgent"

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
                "Please describe the crop and the yield issue you are facing. "
                "For example, low harvest, poor fruit setting, or reduced grain output."
            )
            return self.respond_and_record("", response, image_path)

        clean_query = query.strip()

        try:
            prompt = get_prompt(
                "yield_agent.template",
                chat_history=chat_history or "None",
                query=clean_query,
            )
        except Exception:
            prompt = f"PREVIOUS CONTEXT: {chat_history or 'None'}\nFarmer question: {clean_query}"

        try:
            result, _ = query_groq_text(
                prompt,
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            result = "Yield analysis could not be generated at this time."

        return self.respond_and_record(
            query=clean_query,
            response=result,
            image_path=image_path,
        )
