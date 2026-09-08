"""
RAG 检索增强生成系统 - 完整实现

本模块实现了一个生产级别的 RAG 系统，包括：
- 文档加载和处理
- 向量存储和检索
- 上下文感知的问答生成
- 来源引用和置信度评估

⚠️ Embeddings 说明：
- 默认使用简单的 Fake Embeddings（用于演示）
- 如需高质量结果，请设置 OPENAI_API_KEY 使用 OpenAI Embeddings
"""

import os
from typing import List, Dict, Any, Optional, TypedDict, Literal
from dataclasses import dataclass
from dotenv import load_dotenv

# LangChain 核心导入
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.embeddings import Embeddings

# 文本处理
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 向量存储
from langchain_core.vectorstores import InMemoryVectorStore

# LangGraph
from langgraph.graph import StateGraph, START, END

# 加载环境变量
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
    raise ValueError(
        "\n请先在 .env 文件中设置有效的 GROQ_API_KEY\n"
        "访问 https://console.groq.com/keys 获取免费密钥"
    )

# 初始化模型
model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)


# ==================== 简单 Embeddings（用于演示）====================

class SimpleEmbeddings(Embeddings):
    """
    简单的 Embeddings 实现（用于演示）
    
    使用简单的词频统计生成向量，适合演示目的。
    生产环境请使用 OpenAI 或 HuggingFace Embeddings。
    """
    
    def __init__(self, dimension: int = 384):
        self.dimension = dimension
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """嵌入文档列表"""
        return [self._embed_text(text) for text in texts]
    
    def embed_query(self, text: str) -> List[float]:
        """嵌入查询"""
        return self._embed_text(text)
    
    def _embed_text(self, text: str) -> List[float]:
        """简单的文本嵌入（基于字符频率）"""
        import hashlib
        # 使用文本的hash生成伪随机但确定的向量
        hash_obj = hashlib.md5(text.encode())
        hash_bytes = hash_obj.digest()
        
        # 扩展到目标维度
        vector = []
        for i in range(self.dimension):
            byte_idx = i % len(hash_bytes)
            # 归一化到 [-1, 1]
            value = (hash_bytes[byte_idx] / 255.0) * 2 - 1
            vector.append(value)
        
        return vector


# 选择 Embeddings
def get_embeddings():
    """根据环境选择合适的 Embeddings"""
    if OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here":
        try:
            from langchain_openai import OpenAIEmbeddings
            print("📊 使用 OpenAI Embeddings")
            return OpenAIEmbeddings(model="text-embedding-3-small")
        except ImportError:
            print("⚠️ langchain_openai 未安装，使用简单 Embeddings")
    
    print("📊 使用简单 Embeddings（演示用）")
    return SimpleEmbeddings()


# ==================== 配置类 ====================

@dataclass
class RAGConfig:
    """RAG 系统配置"""
    # 模型配置（使用全局 model）
    temperature: float = 0.1
    
    # 分块配置
    chunk_size: int = 500
    chunk_overlap: int = 100
    
    # 检索配置
    top_k: int = 3
    search_type: str = "similarity"  # similarity, mmr
    
    # 生成配置
    max_tokens: int = 1000

# ==================== 状态定义 ====================

class RAGState(TypedDict):
    """RAG 流程状态"""
    query: str                          # 用户查询
    chat_history: List[Dict[str, str]]  # 对话历史
    documents: List[Document]           # 检索到的文档
    context: str                        # 格式化的上下文
    answer: str                         # 生成的回答
    sources: List[Dict[str, Any]]       # 来源信息
    confidence: float                   # 置信度评分

# ==================== 文档处理模块 ====================

class DocumentProcessor:
    """文档处理器：加载、分块、向量化"""
    
    def __init__(self, config: RAGConfig):
        self.config = config
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        )
        self.embeddings = get_embeddings()  # 使用智能选择的 Embeddings
        self.vector_store = None
    
    def load_documents(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> List[Document]:
        """从文本创建文档"""
        documents = []
        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas and i < len(metadatas) else {"source": f"doc_{i}"}
            documents.append(Document(page_content=text, metadata=metadata))
        return documents
    
    def split_documents(self, documents: List[Document]) -> List[Document]:
        """分割文档为小块"""
        return self.text_splitter.split_documents(documents)
    
    def create_vector_store(self, documents: List[Document]) -> InMemoryVectorStore:
        """创建向量存储"""
        self.vector_store = InMemoryVectorStore.from_documents(
            documents=documents,
            embedding=self.embeddings
        )
        return self.vector_store
    
    def process(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> InMemoryVectorStore:
        """完整处理流程：加载 -> 分块 -> 向量化"""
        print("📄 加载文档...")
        documents = self.load_documents(texts, metadatas)
        print(f"   加载了 {len(documents)} 个文档")
        
        print("✂️  分割文档...")
        chunks = self.split_documents(documents)
        print(f"   生成了 {len(chunks)} 个文本块")
        
        print("🔢 创建向量存储...")
        vector_store = self.create_vector_store(chunks)
        print("   向量存储创建完成")
        
        return vector_store

# ==================== 检索模块 ====================

class Retriever:
    """检索器：从向量存储中检索相关文档"""
    
    def __init__(self, vector_store: InMemoryVectorStore, config: RAGConfig):
        self.vector_store = vector_store
        self.config = config
    
    def retrieve(self, query: str) -> List[Document]:
        """检索相关文档"""
        return self.vector_store.similarity_search(
            query=query,
            k=self.config.top_k
        )
    
    def retrieve_with_scores(self, query: str) -> List[tuple]:
        """检索文档并返回相似度分数"""
        return self.vector_store.similarity_search_with_score(
            query=query,
            k=self.config.top_k
        )

# ==================== 生成模块 ====================

class Generator:
    """生成器：基于上下文生成回答"""
    
    def __init__(self, config: RAGConfig):
        self.config = config
        # 使用全局 model（已配置为 Groq）
        self.llm = model
        
        # RAG 提示模板
        self.rag_prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的问答助手。请基于提供的上下文信息回答用户的问题。

重要规则：
1. 只使用提供的上下文信息来回答问题
2. 如果上下文中没有相关信息，请诚实地说"根据提供的信息，我无法回答这个问题"
3. 回答要准确、简洁、有条理
4. 在回答末尾标注信息来源

上下文信息：
{context}
"""),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{query}")
        ])
        
        # 查询改写提示
        self.rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个查询优化专家。请根据对话历史，将用户的问题改写为一个独立、完整的查询。
            
如果问题本身已经很清晰完整，直接返回原问题。
只返回改写后的查询，不要添加任何解释。"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "原始问题：{query}\n\n请改写为独立完整的查询：")
        ])
    
    def rewrite_query(self, query: str, chat_history: List[Dict[str, str]]) -> str:
        """根据对话历史改写查询"""
        if not chat_history:
            return query
        
        # 转换对话历史格式
        messages = []
        for msg in chat_history[-4:]:  # 只用最近4轮对话
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))
        
        chain = self.rewrite_prompt | self.llm | StrOutputParser()
        return chain.invoke({"query": query, "chat_history": messages})
    
    def generate(self, query: str, context: str, chat_history: List[Dict[str, str]] = None) -> str:
        """生成回答"""
        messages = []
        if chat_history:
            for msg in chat_history[-4:]:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
        
        chain = self.rag_prompt | self.llm | StrOutputParser()
        return chain.invoke({
            "query": query,
            "context": context,
            "chat_history": messages
        })
    
    def evaluate_confidence(self, query: str, context: str, answer: str) -> float:
        """评估回答的置信度"""
        eval_prompt = ChatPromptTemplate.from_messages([
            ("system", """评估以下回答的置信度。考虑：
1. 回答是否基于提供的上下文
2. 信息的相关性和准确性
3. 回答的完整性

只返回一个0到1之间的数字，表示置信度。"""),
            ("human", """上下文：{context}

问题：{query}

回答：{answer}

置信度（0-1）：""")
        ])
        
        chain = eval_prompt | self.llm | StrOutputParser()
        try:
            score = float(chain.invoke({
                "context": context,
                "query": query,
                "answer": answer
            }).strip())
            return min(max(score, 0.0), 1.0)
        except:
            return 0.5

# ==================== RAG 链整合 ====================

class RAGChain:
    """RAG 链：整合所有组件的完整流程"""
    
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.processor = DocumentProcessor(self.config)
        self.retriever = None
        self.generator = Generator(self.config)
        self.graph = None
    
    def index_documents(self, texts: List[str], metadatas: Optional[List[Dict]] = None):
        """索引文档"""
        vector_store = self.processor.process(texts, metadatas)
        self.retriever = Retriever(vector_store, self.config)
        self._build_graph()
    
    def _build_graph(self):
        """构建 LangGraph 流程"""
        
        def process_query(state: RAGState) -> RAGState:
            """处理查询：改写查询（如有对话历史）"""
            query = state["query"]
            chat_history = state.get("chat_history", [])
            
            if chat_history:
                rewritten = self.generator.rewrite_query(query, chat_history)
                print(f"🔄 查询改写：{query} -> {rewritten}")
                state["query"] = rewritten
            
            return state
        
        def retrieve_documents(state: RAGState) -> RAGState:
            """检索相关文档"""
            query = state["query"]
            
            docs = self.retriever.retrieve(query)
            print(f"📚 检索到 {len(docs)} 个相关文档")
            
            state["documents"] = docs
            
            # 格式化上下文
            context_parts = []
            sources = []
            for i, doc in enumerate(docs):
                context_parts.append(f"[文档 {i+1}] {doc.page_content}")
                sources.append({
                    "index": i + 1,
                    "source": doc.metadata.get("source", "unknown"),
                    "content_preview": doc.page_content[:100] + "..."
                })
            
            state["context"] = "\n\n".join(context_parts)
            state["sources"] = sources
            
            return state
        
        def generate_answer(state: RAGState) -> RAGState:
            """生成回答"""
            answer = self.generator.generate(
                query=state["query"],
                context=state["context"],
                chat_history=state.get("chat_history", [])
            )
            state["answer"] = answer
            print("💬 生成回答完成")
            return state
        
        def evaluate_response(state: RAGState) -> RAGState:
            """评估回答置信度"""
            confidence = self.generator.evaluate_confidence(
                query=state["query"],
                context=state["context"],
                answer=state["answer"]
            )
            state["confidence"] = confidence
            print(f"📊 置信度评估：{confidence:.2f}")
            return state
        
        # 构建图
        graph = StateGraph(RAGState)
        
        # 添加节点
        graph.add_node("process_query", process_query)
        graph.add_node("retrieve", retrieve_documents)
        graph.add_node("generate", generate_answer)
        graph.add_node("evaluate", evaluate_response)
        
        # 添加边
        graph.add_edge(START, "process_query")
        graph.add_edge("process_query", "retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", "evaluate")
        graph.add_edge("evaluate", END)
        
        self.graph = graph.compile()
    
    def query(self, question: str, chat_history: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """执行查询"""
        if not self.retriever:
            raise ValueError("请先调用 index_documents() 索引文档")
        
        print(f"\n{'='*60}")
        print(f"🔍 问题：{question}")
        print('='*60)
        
        initial_state = {
            "query": question,
            "chat_history": chat_history or [],
            "documents": [],
            "context": "",
            "answer": "",
            "sources": [],
            "confidence": 0.0
        }
        
        result = self.graph.invoke(initial_state)
        
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "confidence": result["confidence"]
        }

# ==================== 示例数据 ====================

SAMPLE_DOCUMENTS = [
    {
        "text": """LangChain 简介

LangChain 是一个用于开发大型语言模型（LLM）应用的开源框架。它提供了一套标准化的接口和工具，
帮助开发者快速构建基于 LLM 的应用程序。

主要特点：
1. 模块化设计：所有组件都可以独立使用或组合使用
2. 链式调用：支持将多个组件链接在一起形成复杂的工作流
3. 记忆管理：内置多种记忆类型，支持对话历史管理
4. 工具集成：可以轻松集成外部工具和 API

LangChain 1.0 于 2025 年 10 月发布，带来了重大改进：
- 更清晰的 API 设计
- 更好的类型提示支持
- 改进的错误处理
- 与 LangGraph 的深度集成

使用场景包括：聊天机器人、问答系统、文档分析、代码生成等。""",
        "metadata": {"source": "langchain_intro.txt", "topic": "introduction"}
    },
    {
        "text": """LangGraph 介绍

LangGraph 是 LangChain 生态系统中的一个重要组件，专门用于构建有状态的、多步骤的 AI 应用。
它基于图结构来定义工作流，使得复杂的 AI 流程变得清晰和可控。

核心概念：
1. 状态（State）：使用 TypedDict 定义应用状态，在节点间传递
2. 节点（Node）：处理状态的函数，执行具体的业务逻辑
3. 边（Edge）：定义节点之间的连接和流转规则
4. 条件边：根据状态动态决定下一个节点

LangGraph 的优势：
- 可视化流程：图结构使工作流一目了然
- 状态管理：自动处理状态的传递和更新
- 检查点：支持中间状态的保存和恢复
- 人机协作：支持 human-in-the-loop 模式

典型应用场景：
- 多步骤推理
- 多代理协作
- 复杂决策流程
- 带有循环的工作流""",
        "metadata": {"source": "langgraph_intro.txt", "topic": "langgraph"}
    },
    {
        "text": """RAG（检索增强生成）原理

RAG 是一种结合检索和生成的技术，通过从知识库中检索相关信息来增强 LLM 的回答质量。

工作流程：
1. 文档处理：将文档分割成小块，并转换为向量表示
2. 向量存储：将文档向量存入向量数据库
3. 查询检索：用户提问时，检索最相关的文档块
4. 上下文增强：将检索到的内容作为上下文提供给 LLM
5. 回答生成：LLM 基于上下文生成准确的回答

RAG 的优势：
- 减少幻觉：基于真实文档生成回答
- 知识更新：无需重新训练模型即可更新知识
- 来源可追溯：可以引用具体的信息来源
- 成本效益：比微调模型更经济

最佳实践：
- 选择合适的分块策略
- 优化检索算法
- 设计有效的提示模板
- 实现结果重排序""",
        "metadata": {"source": "rag_principles.txt", "topic": "rag"}
    },
    {
        "text": """向量数据库介绍

向量数据库是专门用于存储和检索向量数据的数据库系统，是 RAG 系统的核心组件之一。

主要特点：
1. 高效相似度搜索：支持快速的近似最近邻（ANN）搜索
2. 可扩展性：能够处理数百万甚至数十亿级别的向量
3. 实时更新：支持动态添加和删除向量
4. 元数据过滤：支持基于元数据的过滤查询

常见的向量数据库：
- Chroma：轻量级，适合开发和原型
- Pinecone：云原生，完全托管
- Milvus：开源，高性能
- Weaviate：支持混合搜索
- FAISS：Facebook 开发，适合研究

选择建议：
- 开发阶段：使用 Chroma 或内存向量存储
- 生产环境：根据规模选择 Pinecone 或 Milvus
- 需要混合搜索：考虑 Weaviate

性能优化：
- 选择合适的索引类型
- 调整搜索参数
- 使用批量操作""",
        "metadata": {"source": "vector_db.txt", "topic": "database"}
    }
]

# ==================== 主程序 ====================

def main():
    """主程序：演示 RAG 系统的使用"""
    
    print("=" * 60)
    print("🚀 RAG 检索增强生成系统演示")
    print("=" * 60)
    
    # 1. 初始化 RAG 系统
    print("\n📦 初始化 RAG 系统...")
    config = RAGConfig(
        chunk_size=300,
        chunk_overlap=50,
        top_k=3
    )
    rag = RAGChain(config)
    
    # 2. 索引文档
    print("\n📄 索引示例文档...")
    texts = [doc["text"] for doc in SAMPLE_DOCUMENTS]
    metadatas = [doc["metadata"] for doc in SAMPLE_DOCUMENTS]
    rag.index_documents(texts, metadatas)
    
    # 3. 单轮问答演示
    print("\n" + "=" * 60)
    print("📝 示例 1：单轮问答")
    print("=" * 60)
    
    questions = [
        "什么是 LangChain？它有什么特点？",
        "RAG 系统的工作流程是怎样的？",
        "有哪些常见的向量数据库？"
    ]
    
    for q in questions:
        result = rag.query(q)
        print(f"\n📌 回答：\n{result['answer']}")
        print("\n📎 来源：")
        for src in result['sources']:
            print(f"   - [{src['index']}] {src['source']}")
        print(f"\n📊 置信度：{result['confidence']:.2f}")
        print("-" * 60)
    
    # 4. 多轮对话演示
    print("\n" + "=" * 60)
    print("📝 示例 2：多轮对话（带上下文）")
    print("=" * 60)
    
    chat_history = []
    
    # 第一轮
    q1 = "LangGraph 是什么？"
    print(f"\n👤 用户：{q1}")
    result1 = rag.query(q1, chat_history)
    print(f"\n🤖 助手：{result1['answer']}")
    chat_history.append({"role": "user", "content": q1})
    chat_history.append({"role": "assistant", "content": result1['answer']})
    
    # 第二轮（指代消解）
    q2 = "它的核心概念有哪些？"
    print(f"\n👤 用户：{q2}")
    result2 = rag.query(q2, chat_history)
    print(f"\n🤖 助手：{result2['answer']}")
    chat_history.append({"role": "user", "content": q2})
    chat_history.append({"role": "assistant", "content": result2['answer']})
    
    # 第三轮
    q3 = "在什么场景下使用它比较合适？"
    print(f"\n👤 用户：{q3}")
    result3 = rag.query(q3, chat_history)
    print(f"\n🤖 助手：{result3['answer']}")
    
    print("\n" + "=" * 60)
    print("✅ RAG 系统演示完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
