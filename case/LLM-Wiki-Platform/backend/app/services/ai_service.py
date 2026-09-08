# AI服务 - LangChain 1.0+ 版本
import os
from typing import List, Dict, Any, Optional
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

class AIService:
    """AI服务 - 基于LangChain 1.0+"""
    
    _llm: Optional[ChatOpenAI] = None
    _embeddings: Optional[OpenAIEmbeddings] = None
    _vector_store = None
    
    @classmethod
    def get_llm(cls) -> ChatOpenAI:
        """获取LLM实例"""
        if cls._llm is None:
            cls._llm = ChatOpenAI(
                model=os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                temperature=0.7,
                max_tokens=2000,
                api_key=os.getenv('OPENAI_API_KEY'),
                base_url=os.getenv('OPENAI_BASE_URL')
            )
        return cls._llm
    
    @classmethod
    def get_embeddings(cls) -> OpenAIEmbeddings:
        """获取Embedding实例"""
        if cls._embeddings is None:
            cls._embeddings = OpenAIEmbeddings(
                model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
                api_key=os.getenv('OPENAI_API_KEY'),
                base_url=os.getenv('OPENAI_BASE_URL')
            )
        return cls._embeddings
    
    @classmethod
    def get_vector_store(cls):
        """获取向量存储实例（需要 Milvus 服务 + langchain-milvus 包，不可用时返回 None）"""
        if cls._vector_store is None:
            try:
                from langchain_milvus import Milvus
                from pymilvus import connections

                host = os.getenv('MILVUS_HOST', 'localhost')
                port = os.getenv('MILVUS_PORT', '19530')
                uri = f"http://{host}:{port}"

                # langchain-milvus 内部部分路径（集合已存在时）依赖 pymilvus ORM 全局连接
                try:
                    connections.connect("default", uri=uri)
                except Exception:
                    pass

                cls._vector_store = Milvus(
                    embedding_function=cls.get_embeddings(),
                    collection_name=os.getenv('MILVUS_COLLECTION', 'wiki_embeddings'),
                    # langchain-milvus >=0.3 使用 MilvusClient，连接参数须为 uri 格式
                    connection_args={"uri": uri}
                )
            except Exception as e:
                print(f"[AIService] Milvus 不可用，向量检索已降级: {e}")
                return None
        return cls._vector_store
    
    @staticmethod
    def search_similar_documents(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索相似文档"""
        try:
            vector_store = AIService.get_vector_store()
            results = vector_store.similarity_search_with_score(query, k=top_k)
            
            search_results = []
            for doc, score in results:
                search_results.append({
                    'document_id': doc.metadata.get('document_id', 0),
                    'content': doc.page_content,
                    'score': float(score),
                    'metadata': doc.metadata
                })
            
            return search_results
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    @staticmethod
    def build_context(search_results: List[Dict[str, Any]]) -> str:
        """构建上下文"""
        context_parts = []
        for i, result in enumerate(search_results, 1):
            context_parts.append(f"[文档{i}] {result['content']}")
        
        return "\n\n".join(context_parts)
    
    @staticmethod
    def generate_answer(question: str, context: str) -> Dict[str, Any]:
        """生成回答 - 使用LangChain 1.0+ LCEL"""
        try:
            llm = AIService.get_llm()
            
            prompt_template = """基于以下上下文回答用户问题。
如果上下文中没有相关信息，请说明您不知道答案，不要编造答案。
请提供准确、详细的回答，并在可能的情况下引用来源。

上下文:
{context}

问题: {question}

请提供详细、准确的回答："""
            
            prompt = PromptTemplate(
                template=prompt_template,
                input_variables=["context", "question"]
            )
            
            # 使用LCEL (LangChain Expression Language)
            chain = prompt | llm | StrOutputParser()
            
            response = chain.invoke({
                "context": context,
                "question": question
            })
            
            return {
                'answer': response,
                'confidence': 0.85,
                'model_used': os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                'tokens_used': 0  # 新版API需要额外处理token计数
            }
        except Exception as e:
            return {
                'answer': f'生成回答时出错: {str(e)}',
                'confidence': 0.0,
                'model_used': os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                'tokens_used': 0
            }
    
    @staticmethod
    def process_document_for_embedding(document_id: int, content: str) -> tuple[bool, Any]:
        """处理文档生成嵌入"""
        try:
            # 文本分割
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                length_function=len,
            )
            chunks = text_splitter.split_text(content)
            
            # 生成嵌入并存储
            vector_store = AIService.get_vector_store()
            
            # 创建LangChain文档对象
            documents = []
            for i, chunk in enumerate(chunks):
                doc = LCDocument(
                    page_content=chunk,
                    metadata={"document_id": document_id, "chunk_index": i}
                )
                documents.append(doc)
            
            # 添加到向量存储
            vector_store.add_documents(documents)
            
            return True, len(chunks)
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def remove_document_embeddings(document_id: int) -> bool:
        """删除文档的所有向量（用于更新/删除文档时）"""
        try:
            vector_store = AIService.get_vector_store()
            if vector_store is None:
                return False
            return bool(vector_store.delete(expr=f"document_id == {int(document_id)}"))
        except Exception as e:
            print(f"Remove embeddings error: {e}")
            return False
    
    @staticmethod
    def reset():
        """重置服务（用于测试或重新连接）"""
        AIService._llm = None
        AIService._embeddings = None
        AIService._vector_store = None