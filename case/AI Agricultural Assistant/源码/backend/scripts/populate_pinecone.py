"""
One-time script to populate Pinecone index from subsidies.json.
Run: python -m backend.scripts.populate_pinecone
Requires: PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_ENVIRONMENT (if applicable)
"""
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from pinecone import Pinecone, ServerlessSpec

from backend.core.config import settings

DATA_PATH = os.path.join(os.path.dirname(__file__), "../../data/subsidies.json")
EMBEDDING_DIM = 384


def load_documents():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    docs = []
    for item in raw:
        scheme_name = item.get("scheme_name", "Unknown Scheme")
        eligibility = item.get("eligibility", "Not Provided")
        benefits = item.get("benefits", "Not Provided")
        notes = item.get("notes", "")
        content = f"Scheme: {scheme_name}\nEligibility: {eligibility}\nBenefits: {benefits}\nNotes: {notes}\n"
        docs.append(Document(page_content=content, metadata=item))
    return docs


def main():
    if not settings.PINECONE_API_KEY:
        print("Error: PINECONE_API_KEY not set.")
        sys.exit(1)

    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index_name = settings.PINECONE_INDEX_NAME or "agrigpt-subsidies"

    if index_name not in [i.name for i in pc.list_indexes()]:
        print(f"Creating index {index_name}...")
        pc.create_index(
            name=index_name,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print("Index created. Waiting for readiness...")
        import time
        time.sleep(10)

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L12-v2")
    docs = load_documents()

    from langchain_pinecone import PineconeVectorStore

    vector_store = PineconeVectorStore.from_existing_index(
        index_name=index_name,
        embedding=embeddings,
    )
    vector_store.add_documents(docs)
    print(f"Added {len(docs)} documents to Pinecone index '{index_name}'.")


if __name__ == "__main__":
    main()
