# AI服务 - 直接使用 pymilvus MilvusClient
import os
from typing import List, Dict, Any, Optional
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument
from langchain_core.output_parsers import StrOutputParser

class AIService:
    """AI服务"""
    
    _llm: Optional[ChatOpenAI] = None
    _embeddings: Optional[OpenAIEmbeddings] = None
    _milvus_client = None
    
    @classmethod
    def get_llm(cls) -> ChatOpenAI:
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
        if cls._embeddings is None:
            cls._embeddings = OpenAIEmbeddings(
                model=os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small'),
                api_key=os.getenv('OPENAI_API_KEY'),
                base_url=os.getenv('OPENAI_BASE_URL')
            )
        return cls._embeddings
    
    @classmethod
    def get_milvus_client(cls):
        if cls._milvus_client is None:
            try:
                from pymilvus import MilvusClient
                host = os.getenv('MILVUS_HOST', 'localhost')
                port = os.getenv('MILVUS_PORT', '19530')
                uri = f"http://{host}:{port}"
                cls._milvus_client = MilvusClient(uri=uri)
                print(f"[AIService] Milvus connected: {uri}")
            except Exception as e:
                print(f"[AIService] Milvus 连接失败: {e}")
                return None
        return cls._milvus_client
    
    @classmethod
    def get_collection_name(cls):
        return os.getenv('MILVUS_COLLECTION', 'wiki_embeddings')
    
    @staticmethod
    def search_similar_documents(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            client = AIService.get_milvus_client()
            if client is None:
                print("[AIService] Milvus client unavailable")
                return []
            
            embeddings = AIService.get_embeddings()
            query_vector = embeddings.embed_query(query)
            
            collection = AIService.get_collection_name()
            
            results = client.search(
                collection_name=collection,
                data=[query_vector],
                limit=top_k,
                output_fields=["text", "document_id", "chunk_index"]
            )
            
            search_results = []
            if results and len(results) > 0:
                for hit in results[0]:
                    text = hit.get("entity", {}).get("text", "")
                    search_results.append({
                        'document_id': hit.get("entity", {}).get("document_id", 0),
                        'content': text,
                        'snippet': text[:200] + '...' if len(text) > 200 else text,
                        'score': float(hit.get("distance", 0)),
                        'metadata': {}
                    })
            
            print(f"[AIService] Search found {len(search_results)} results")
            return search_results
        except Exception as e:
            print(f"Search error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    @staticmethod
    def build_context(search_results: List[Dict[str, Any]]) -> str:
        context_parts = []
        for i, result in enumerate(search_results, 1):
            context_parts.append(f"[文档{i}] {result['content']}")
        return "\n\n".join(context_parts)
    
    @staticmethod
    def generate_answer(question: str, context: str) -> Dict[str, Any]:
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
            
            chain = prompt | llm | StrOutputParser()
            
            response = chain.invoke({
                "context": context,
                "question": question
            })
            
            return {
                'answer': response,
                'confidence': 0.85,
                'model_used': os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                'tokens_used': 0
            }
        except Exception as e:
            return {
                'answer': f'生成回答时出错: {str(e)}',
                'confidence': 0.0,
                'model_used': os.getenv('OPENAI_MODEL', 'gpt-5-mini'),
                'tokens_used': 0
            }
    
    @staticmethod
    def generate_answer_stream(question: str, context: str):
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
            
            chain = prompt | llm
            
            for chunk in chain.stream({"context": context, "question": question}):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            yield f'生成回答时出错: {str(e)}'
    
    @staticmethod
    def process_document_for_embedding(document_id: int, content: str) -> tuple[bool, Any]:
        try:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                length_function=len,
            )
            chunks = text_splitter.split_text(content)
            
            embeddings = AIService.get_embeddings()
            vectors = embeddings.embed_documents(chunks)
            
            client = AIService.get_milvus_client()
            if client is None:
                return False, "Milvus client unavailable"
            
            data = []
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                data.append({
                    "text": chunk,
                    "vector": vector,
                    "document_id": document_id,
                    "chunk_index": i
                })
            
            collection = AIService.get_collection_name()
            client.insert(collection_name=collection, data=data)
            
            return True, len(chunks)
        except Exception as e:
            print(f"Embedding error: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)
    
    @staticmethod
    def remove_document_embeddings(document_id: int) -> bool:
        try:
            client = AIService.get_milvus_client()
            if client is None:
                return False
            collection = AIService.get_collection_name()
            client.delete(
                collection_name=collection,
                filter=f"document_id == {int(document_id)}"
            )
            return True
        except Exception as e:
            print(f"Remove embeddings error: {e}")
            return False
    
    @staticmethod
    def reset():
        AIService._llm = None
        AIService._embeddings = None
        AIService._milvus_client = None
