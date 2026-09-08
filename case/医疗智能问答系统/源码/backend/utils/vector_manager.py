#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pgvector 向量管理器
用于处理文档向量化、存储和检索
"""

import os
import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from models.document import Document
from models.knowledge_base import KnowledgeBase
from models.document_vector import DocumentVector, get_vector_session

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VectorManager:
    """pgvector 向量管理器"""
    
    def __init__(self, embedding_model: str = None, dimension: int = None):
        """
        初始化向量管理器
        
        Args:
            embedding_model: 嵌入模型名称
            dimension: 向量维度
        """
        self.embedding_model = embedding_model or os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')
        self.dimension = dimension or int(os.getenv('EMBEDDING_DIMENSION', '1536'))
        self.embeddings_api_url = os.getenv('EMBEDDINGS_API_URL', 'http://127.0.0.1:11434/api/embeddings')
        
        # 默认文本分割参数
        self.default_chunk_size = 1000
        self.default_chunk_overlap = 200
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        生成文本嵌入向量
        
        支持两种 API 格式:
        1. OpenAI 风格: {model, input}
        2. Ollama 风格: {model, prompt}
        
        Args:
            text: 要嵌入的文本
            
        Returns:
            向量列表或 None（如果失败）
        """
        try:
            if not self.embeddings_api_url or not self.embedding_model:
                logger.error("Embedding API URL or model not configured")
                return None
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            # 优先尝试 Ollama 风格（使用 prompt 参数）
            payload_ollama = {
                'model': self.embedding_model,
                'prompt': text
            }
            
            try:
                resp = requests.post(
                    self.embeddings_api_url,
                    headers=headers,
                    data=json.dumps(payload_ollama),
                    timeout=30
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    # 检查响应格式
                    if 'embedding' in data and isinstance(data['embedding'], list):
                        logger.debug(f"Generated embedding with dimension {len(data['embedding'])}")
                        return data['embedding']
                    # 兼容返回 data 数组
                    if 'data' in data and data['data']:
                        emb = data['data'][0].get('embedding')
                        if isinstance(emb, list):
                            logger.debug(f"Generated embedding with dimension {len(emb)}")
                            return emb
                else:
                    logger.debug(f"Ollama style API failed with status {resp.status_code}")
            except Exception as e:
                logger.debug(f"Ollama style API request failed: {e}")
            
            # 尝试 OpenAI 风格（使用 input 参数）
            payload_openai = {
                'model': self.embedding_model,
                'input': text
            }
            
            try:
                resp2 = requests.post(
                    self.embeddings_api_url,
                    headers=headers,
                    data=json.dumps(payload_openai),
                    timeout=30
                )
                
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    # OpenAI style: { data: [ { embedding: [...] } ] }
                    if isinstance(data2, dict) and 'data' in data2 and data2['data']:
                        emb2 = data2['data'][0].get('embedding')
                        if isinstance(emb2, list):
                            logger.debug(f"Generated embedding with dimension {len(emb2)}")
                            return emb2
                    # 一些服务直接返回 { embedding: [...] }
                    if 'embedding' in data2 and isinstance(data2['embedding'], list):
                        logger.debug(f"Generated embedding with dimension {len(data2['embedding'])}")
                        return data2['embedding']
                else:
                    logger.debug(f"OpenAI style API failed with status {resp2.status_code}")
            except Exception as e:
                logger.debug(f"OpenAI style API request failed: {e}")
            
            logger.error("Failed to generate embedding with both API styles")
            return None
            
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None
    
    def split_text(self, text: str, chunk_size: Optional[int] = None, 
                   chunk_overlap: Optional[int] = None) -> List[str]:
        """
        将文本分割成块
        
        Args:
            text: 要分割的文本
            chunk_size: 块大小（不传则使用默认值）
            chunk_overlap: 重叠大小（不传则使用默认值）
            
        Returns:
            文本块列表
        """
        try:
            cs = chunk_size if chunk_size is not None else self.default_chunk_size
            co = chunk_overlap if chunk_overlap is not None else self.default_chunk_overlap
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=cs,
                chunk_overlap=co,
                length_function=len,
                separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
            )
            
            chunks = text_splitter.split_text(text)
            logger.info(f"Split text into {len(chunks)} chunks (size={cs}, overlap={co})")
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to split text: {e}")
            return [text]  # 如果分割失败，返回原始文本

    def process_document(self, document: Document, kb: KnowledgeBase, 
                        chunk_size: Optional[int] = None,
                        chunk_overlap: Optional[int] = None) -> bool:
        """
        处理文档，生成并存储向量
        
        Args:
            document: 文档对象
            kb: 知识库对象
            chunk_size: 可选的块大小
            chunk_overlap: 可选的重叠大小
            
        Returns:
            是否成功
        """
        vector_session = None
        try:
            # 更新文档状态为处理中
            document.vector_status = 'processing'
            document.vector_error = None
            
            # 分割文本
            text = document.content
            if not text or not text.strip():
                logger.warning(f"Document {document.id} has no content")
                document.vector_status = 'failed'
                document.vector_error = 'No content to vectorize'
                return False
            
            chunks = self.split_text(text, chunk_size, chunk_overlap)
            
            if not chunks:
                logger.warning(f"Document {document.id} produced no chunks")
                document.vector_status = 'failed'
                document.vector_error = 'Text splitting produced no chunks'
                return False
            
            # 删除已存在的向量
            self.delete_document_vectors(document.id)
            
            # 获取向量数据库会话
            vector_session = get_vector_session()
            
            # 处理每个文本块
            successful_chunks = 0
            for i, chunk in enumerate(chunks):
                try:
                    # 生成嵌入向量
                    embedding = self.generate_embedding(chunk)
                    
                    if embedding is None:
                        logger.warning(f"Failed to generate embedding for chunk {i} of document {document.id}")
                        continue
                    
                    # 创建向量对象
                    vector_obj = DocumentVector(
                        id=str(uuid.uuid4()),
                        document_id=document.id,
                        kb_id=document.kb_id,
                        chunk_index=i,
                        chunk_text=chunk,
                        embedding=embedding,
                        meta_data={
                            'title': document.title,
                            'category': document.category,
                            'author': document.author,
                            'kb_name': kb.name if kb else None
                        }
                    )
                    
                    # 保存到数据库
                    vector_session.add(vector_obj)
                    successful_chunks += 1
                    
                except Exception as e:
                    logger.error(f"Failed to process chunk {i} of document {document.id}: {e}")
                    continue
            
            # 提交所有向量
            if successful_chunks > 0:
                vector_session.commit()
                
                # 更新文档状态
                document.chunk_count = successful_chunks
                document.vector_status = 'completed'
                logger.info(f"Successfully processed document {document.id} with {successful_chunks}/{len(chunks)} chunks")
                return True
            else:
                vector_session.rollback()
                document.vector_status = 'failed'
                document.vector_error = 'Failed to generate embeddings for all chunks'
                logger.error(f"Failed to process any chunks for document {document.id}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to process document {document.id}: {e}")
            if vector_session:
                vector_session.rollback()
            document.vector_status = 'failed'
            document.vector_error = str(e)
            return False
            
        finally:
            if vector_session:
                vector_session.close()
    
    def delete_document_vectors(self, document_id: str) -> bool:
        """
        删除文档的所有向量
        
        Args:
            document_id: 文档ID
            
        Returns:
            是否成功
        """
        vector_session = None
        try:
            vector_session = get_vector_session()
            
            # 删除所有相关向量
            deleted_count = vector_session.query(DocumentVector).filter(
                DocumentVector.document_id == document_id
            ).delete()
            
            vector_session.commit()
            logger.info(f"Deleted {deleted_count} vectors for document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vectors for document {document_id}: {e}")
            if vector_session:
                vector_session.rollback()
            return False
            
        finally:
            if vector_session:
                vector_session.close()
    
    def delete_kb_vectors(self, kb_id: str) -> bool:
        """
        删除知识库的所有向量
        
        Args:
            kb_id: 知识库ID
            
        Returns:
            是否成功
        """
        vector_session = None
        try:
            vector_session = get_vector_session()
            
            # 删除所有相关向量
            deleted_count = vector_session.query(DocumentVector).filter(
                DocumentVector.kb_id == kb_id
            ).delete()
            
            vector_session.commit()
            logger.info(f"Deleted {deleted_count} vectors for knowledge base {kb_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vectors for knowledge base {kb_id}: {e}")
            if vector_session:
                vector_session.rollback()
            return False
            
        finally:
            if vector_session:
                vector_session.close()

    def search_similar(self, query: str, kb_id: Optional[str] = None, 
                      limit: int = 10, similarity_threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        向量相似度搜索
        
        使用 pgvector 的余弦相似度搜索相似文档
        
        Args:
            query: 查询文本
            kb_id: 可选的知识库ID（限制搜索范围）
            limit: 返回结果数量
            similarity_threshold: 相似度阈值（0-1）
            
        Returns:
            相似文档列表，包含文档信息和相关度分数
        """
        vector_session = None
        try:
            # 生成查询向量
            query_embedding = self.generate_embedding(query)
            
            if query_embedding is None:
                logger.warning("Failed to generate query embedding, returning empty results")
                return []
            
            vector_session = get_vector_session()
            
            # 构建查询
            # 使用 pgvector 的余弦距离操作符 <=>
            # 余弦距离 = 1 - 余弦相似度，所以距离越小越相似
            query_sql = text("""
                SELECT 
                    dv.document_id,
                    dv.kb_id,
                    dv.chunk_text,
                    dv.chunk_index,
                    dv.meta_data,
                    (1 - (dv.embedding <=> :query_embedding)) as similarity
                FROM document_vectors dv
                WHERE (:kb_id IS NULL OR dv.kb_id = :kb_id)
                    AND (1 - (dv.embedding <=> :query_embedding)) >= :threshold
                ORDER BY dv.embedding <=> :query_embedding
                LIMIT :limit
            """)
            
            # 执行查询
            result = vector_session.execute(
                query_sql,
                {
                    'query_embedding': str(query_embedding),
                    'kb_id': kb_id,
                    'threshold': similarity_threshold,
                    'limit': limit * 3  # 获取更多结果用于聚合
                }
            )
            
            # 处理结果
            chunks = []
            for row in result:
                metadata = row.meta_data if isinstance(row.meta_data, dict) else {}
                chunks.append({
                    'document_id': row.document_id,
                    'kb_id': row.kb_id,
                    'title': metadata.get('title', ''),
                    'content': row.chunk_text,  # 直接使用块内容，不聚合
                    'category': metadata.get('category', ''),
                    'author': metadata.get('author', ''),
                    'chunk_index': row.chunk_index,
                    'similarity': float(row.similarity),
                    'search_type': 'vector'
                })
            
            # 按相似度排序所有块，而不是按文档聚合
            chunks.sort(key=lambda x: x['similarity'], reverse=True)
            
            logger.info(f"Vector search found {len(chunks)} chunks for query: {query[:50]}...")
            return chunks[:limit]  # 返回最相关的块，而不是聚合后的文档
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
            
        finally:
            if vector_session:
                vector_session.close()
    
    def hybrid_search(self, query: str, kb_id: Optional[str] = None,
                     limit: int = 10, similarity_threshold: float = 0.7) -> List[Dict[str, Any]]:
        """
        混合搜索（向量搜索 + SQL 全文搜索）
        
        先进行向量搜索，如果结果不足，补充 SQL 全文搜索结果
        
        Args:
            query: 查询文本
            kb_id: 可选的知识库ID
            limit: 返回结果数量
            similarity_threshold: 向量搜索相似度阈值
            
        Returns:
            搜索结果列表
        """
        try:
            # 1. 向量搜索
            vector_results = self.search_similar(query, kb_id, limit, similarity_threshold)
            
            # 如果向量搜索结果足够，直接返回
            if len(vector_results) >= limit:
                return vector_results[:limit]
            
            # 2. 补充 SQL 全文搜索
            logger.info(f"Vector search returned {len(vector_results)} results, supplementing with SQL search")
            
            from models.base import db
            
            # 构建 SQL 查询
            sql_query = db.session.query(Document).filter(
                Document.status == 'published'
            )
            
            if kb_id:
                sql_query = sql_query.filter(Document.kb_id == kb_id)
            
            # 排除已经在向量搜索结果中的文档
            vector_doc_ids = [r['document_id'] for r in vector_results]
            if vector_doc_ids:
                sql_query = sql_query.filter(~Document.id.in_(vector_doc_ids))
            
            # 全文搜索（简单的 LIKE 查询）
            search_pattern = f"%{query}%"
            sql_query = sql_query.filter(
                db.or_(
                    Document.title.like(search_pattern),
                    Document.content.like(search_pattern)
                )
            )
            
            # 获取补充结果
            sql_docs = sql_query.limit(limit - len(vector_results)).all()
            
            # 转换为统一格式
            sql_results = []
            for doc in sql_docs:
                sql_results.append({
                    'document_id': doc.id,
                    'kb_id': doc.kb_id,
                    'title': doc.title,
                    'content': doc.content[:500],  # 截取前500字符
                    'category': doc.category,
                    'author': doc.author,
                    'similarity': 0.5,  # SQL 搜索给予固定的较低相似度
                    'search_type': 'sql'
                })
            
            # 合并结果
            combined_results = vector_results + sql_results
            
            logger.info(f"Hybrid search returned {len(combined_results)} total results "
                       f"({len(vector_results)} vector + {len(sql_results)} SQL)")
            
            return combined_results[:limit]
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []
    
    def _aggregate_chunks_by_document(self, chunks: List[Dict], limit: int) -> List[Dict[str, Any]]:
        """
        按文档聚合文本块，返回每个文档最相关的单个文本块
        
        Args:
            chunks: 文本块列表
            limit: 返回文档数量限制
            
        Returns:
            聚合后的文档列表，每个文档包含最相关的单个文本块
        """
        try:
            # 按文档ID分组
            doc_chunks = {}
            for chunk in chunks:
                doc_id = chunk['document_id']
                if doc_id not in doc_chunks:
                    doc_chunks[doc_id] = []
                doc_chunks[doc_id].append(chunk)
            
            # 为每个文档选择最相关的文本块
            results = []
            for doc_id, doc_chunk_list in doc_chunks.items():
                # 按相似度排序，取最相关的块
                doc_chunk_list.sort(key=lambda x: x['similarity'], reverse=True)
                top_chunk = doc_chunk_list[0]  # 只取最相关的单个块
                
                # 获取元数据
                metadata = top_chunk.get('metadata', {})
                
                results.append({
                    'document_id': doc_id,
                    'kb_id': top_chunk['kb_id'],
                    'title': metadata.get('title', ''),
                    'content': top_chunk['chunk_text'],  # 使用单个块的内容，而不是合并
                    'category': metadata.get('category', ''),
                    'author': metadata.get('author', ''),
                    'similarity': top_chunk['similarity'],
                    'chunk_index': top_chunk['chunk_index'],  # 添加块索引
                    'total_chunks': len(doc_chunk_list),  # 该文档的总匹配块数
                    'search_type': 'vector'
                })
            
            # 按相似度排序
            results.sort(key=lambda x: x['similarity'], reverse=True)
            
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Failed to aggregate chunks: {e}")
            return []


# 全局向量管理器实例
_vector_manager = None


def get_vector_manager(embedding_model: str = None, dimension: int = 1536) -> VectorManager:
    """
    获取全局向量管理器实例
    
    Args:
        embedding_model: 嵌入模型名称
        dimension: 向量维度
        
    Returns:
        向量管理器实例
    """
    global _vector_manager
    
    if _vector_manager is None:
        _vector_manager = VectorManager(embedding_model, dimension)
    
    return _vector_manager
