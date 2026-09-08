"""问答提示词与 LLM 工厂：定义 RAG 的提示模板与模型构造。"""
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from src.config import settings

PROMPT_TEMPLATE = """你是一个专业的「智能笔记助手」。请严格依据下方【笔记上下文】回答用户的问题。

要求：
1. 只能使用上下文中提供的信息，禁止编造、禁止引入笔记之外的知识。
2. 若上下文中没有可用信息，请明确告知「笔记中未找到相关内容」，不要猜测。
3. 回答使用简体中文，结构清晰；可在关键结论后标注来源文件，例如（来源：xxx.md）。
4. 如内容较多，请使用分点 / 小标题组织。

【笔记上下文】
{context}

【用户问题】
{question}

【回答】"""


def get_llm(temperature: float = 0.3, streaming: bool = False) -> ChatOpenAI:
    """构造聊天模型。统一使用 gpt-5-mini（由 CHAT_MODEL 配置）。"""
    return ChatOpenAI(
        model=settings.CHAT_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
        streaming=streaming,
    )


def build_prompt() -> ChatPromptTemplate:
    """构造 RAG 提示词模板。"""
    return ChatPromptTemplate.from_template(PROMPT_TEMPLATE)


def format_docs(documents) -> str:
    """将检索到的文档拼装为带来源标注的上下文。"""
    blocks = []
    for i, d in enumerate(documents, 1):
        src = d.metadata.get("source", "未知来源")
        blocks.append(f"[笔记 {i} | 来源: {src}]\n{d.page_content}")
    return "\n\n".join(blocks)
