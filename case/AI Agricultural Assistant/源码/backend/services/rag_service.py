import json
import os
from typing import List, Dict, Optional
import unicodedata
import re

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from backend.core.config import settings

DATA_PATH = os.path.join(os.path.dirname(__file__), "../data/subsidies.json")
VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "../data/faiss_index")

# HuggingFace MiniLM dimension for Pinecone
EMBEDDING_DIM = 384


def _clean_query(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _load_subsidy_documents() -> List[Document]:
    """Load subsidy documents from JSON."""
    if not os.path.exists(DATA_PATH):
        return []

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[RAG] Failed to load subsidies.json: {e}")
        return []

    if not isinstance(raw_data, list):
        print("[RAG] subsidies.json must be a JSON array")
        return []

    documents: List[Document] = []
    for item in raw_data:
        scheme_name = item.get("scheme_name", "Unknown Scheme")
        eligibility = item.get("eligibility", "Not Provided")
        benefits = item.get("benefits", "Not Provided")
        notes = item.get("notes", "")

        content = (
            f"Scheme: {scheme_name}\n"
            f"Eligibility: {eligibility}\n"
            f"Benefits: {benefits}\n"
            f"Notes: {notes}\n"
        )
        documents.append(Document(page_content=content, metadata=item))

    return documents


class RAG:
    """
    RAG singleton for subsidy retrieval.
    Supports FAISS (default) or Pinecone when PINECONE_API_KEY is set.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RAG, cls).__new__(cls)
            cls._instance.initialize()
        return cls._instance

    def initialize(self):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L12-v2"
        )

        self.vector_store = None
        self._use_pinecone = bool(
            settings.PINECONE_API_KEY and settings.PINECONE_INDEX_NAME
        )

        if self._use_pinecone:
            self._init_pinecone()
        else:
            self._init_faiss()

    def _init_pinecone(self):
        """Initialize Pinecone vector store."""
        try:
            from pinecone import Pinecone
            from langchain_pinecone import PineconeVectorStore

            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            index_name = settings.PINECONE_INDEX_NAME

            if index_name not in [idx.name for idx in pc.list_indexes()]:
                print(f"[RAG] Pinecone index '{index_name}' not found.")
                print("[RAG] Falling back to FAISS.")
                self._use_pinecone = False
                self._init_faiss()
                return

            self.vector_store = PineconeVectorStore.from_existing_index(
                index_name=index_name,
                embedding=self.embeddings,
            )

            print("[RAG] Using Pinecone vector store.")
            print("[RAG] Run: python -m backend.scripts.populate_pinecone to populate index.")
        except Exception as e:
            print(f"[RAG] Pinecone init failed: {e}. Falling back to FAISS.")
            self._use_pinecone = False
            self._init_faiss()

    def _init_faiss(self):
        """Initialize FAISS vector store."""
        if os.path.exists(VECTOR_DB_PATH):
            try:
                print("[RAG] Loading existing FAISS index...")
                self.vector_store = FAISS.load_local(
                    VECTOR_DB_PATH,
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
                print("[RAG] FAISS index loaded.")
                return
            except Exception as e:
                print(f"[RAG] Failed to load FAISS index: {e}")
                print("[RAG] Rebuilding index...")
                try:
                    import shutil
                    shutil.rmtree(VECTOR_DB_PATH)
                except Exception:
                    pass

        docs = _load_subsidy_documents()
        if not docs:
            print(f"[RAG] subsidies.json not found at: {DATA_PATH}")
            return

        print("[RAG] Building FAISS index...")
        self.vector_store = FAISS.from_documents(docs, self.embeddings)
        self.vector_store.save_local(VECTOR_DB_PATH)
        print("[RAG] FAISS index built and saved.")

    def retrieve(self, query: str, k: int = 2) -> List[Dict[str, str]]:
        if not query or not query.strip():
            return []

        query_clean = _clean_query(query.strip() + " india agriculture subsidy")

        if not self.vector_store:
            print("[RAG] Vector store not loaded.")
            return []

        try:
            if self._use_pinecone:
                docs = self.vector_store.similarity_search(query_clean, k=k)
                docs_with_scores = [(doc, 0.0) for doc in docs]
            else:
                docs_with_scores = self.vector_store.similarity_search_with_score(
                    query_clean, k=k
                )
        except Exception as e:
            print(f"[RAG] Retrieval error: {e}")
            return []

        results: List[Dict[str, str]] = []

        for item in docs_with_scores:
            if len(item) == 2:
                doc, score = item
            else:
                doc, score = item[0], 0.0

            if not self._use_pinecone and score > 0.7:
                continue

            meta = doc.metadata if isinstance(doc.metadata, dict) else {}

            results.append({
                "scheme_name": str(meta.get("scheme_name", "Unknown Scheme")),
                "eligibility": str(meta.get("eligibility", "Not Provided")),
                "benefits": str(meta.get("benefits", "Not Provided")),
                "application_steps": str(meta.get("application_steps", "")),
                "documents": str(meta.get("documents", "")),
                "notes": str(meta.get("notes", "")),
            })

        return results


rag_service = RAG()
