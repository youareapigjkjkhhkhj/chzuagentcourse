from backend.services.text_service import query_groq_text
from backend.services.vision_service import query_groq_image
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.prompt_loader import get_prompt


class PestAgent(AgriAgentBase):
    """
    PestAgent:
    Handles pest, disease, and visible symptom analysis.
    Image input ALWAYS takes priority over text.
    """

    name = "PestAgent"

    def handle_query(
        self,
        query: str = None,
        image_path: str = None,
        chat_history: str = None,
        request_id: str = None,
        session_id: str = None,
        **kwargs,
    ) -> str:

        if not query and not image_path:
            response = (
                "Please upload a crop image or describe visible symptoms such as "
                "yellowing, spots, holes, insects, wilting, or abnormal leaf color."
            )
            return self.respond_and_record("", response, image_path)

        if image_path:
            try:
                vision_prompt = get_prompt("pest_agent.vision_prompt")
            except Exception:
                vision_prompt = (
                    "You are AgriGPT Vision, an expert agricultural diagnostics assistant. "
                    "Analyze this crop image in detail. "
                    "1. DESCRIBE symptoms clearly. "
                    "2. IDENTIFY the likely issue if visual evidence is strong. "
                    "3. ESTIMATE severity (mild, moderate, severe). "
                )

            try:
                result, _ = query_groq_image(
                    image_path,
                    vision_prompt,
                    request_id=request_id,
                    session_id=session_id,
                )
            except Exception:
                result = "The image could not be analyzed clearly."

            return self.respond_and_record(
                "Image-based symptom observation",
                result,
                image_path=image_path,
            )

        clean_query = query.strip()

        try:
            text_prompt = get_prompt(
                "pest_agent.text_template",
                chat_history=chat_history or "None",
                query=clean_query,
            )
        except Exception:
            text_prompt = f"CONTEXT: {chat_history or 'None'}\nFarmer description: {clean_query}"

        try:
            result, _ = query_groq_text(
                text_prompt,
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            result = "Pest analysis could not be generated at this time."

        return self.respond_and_record(
            clean_query,
            result,
            image_path=image_path,
        )
