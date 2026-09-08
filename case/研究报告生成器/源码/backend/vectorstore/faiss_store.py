from collections import Counter
import math

import faiss

from vectorstore.embeddings import HashingEmbeddingModel, tokenize_for_retrieval


class ResearchVectorStore:
    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model or HashingEmbeddingModel()
        self.index = None
        self.documents = []
        self.doc_token_counts = []
        self.doc_lengths = []
        self.idf = {}
        self.avg_doc_length = 0.0

    def add_documents(self, documents):
        self.documents = [doc for doc in documents if doc.get("text")]
        if not self.documents:
            self.index = None
            return

        vectors = self.embedding_model.embed_documents(
            [self._retrieval_text(doc) for doc in self.documents]
        )
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)
        self._build_lexical_index()

    def search(self, query, top_k=8):
        if self.index is None or not self.documents:
            return []

        limit = min(top_k, len(self.documents))
        candidate_count = len(self.documents)
        query_vector = self.embedding_model.embed_query(query).reshape(1, -1)
        vector_scores, vector_indices = self.index.search(query_vector, candidate_count)
        vector_by_index = {
            int(index): float(score)
            for score, index in zip(vector_scores[0], vector_indices[0])
            if index >= 0
        }

        query_tokens = tokenize_for_retrieval(query)
        bm25_scores = [
            self._bm25_score(query_tokens, index)
            for index in range(len(self.documents))
        ]
        overlap_scores = [
            self._overlap_score(query_tokens, index)
            for index in range(len(self.documents))
        ]

        normalized_vector = _minmax([
            vector_by_index.get(index, 0.0)
            for index in range(len(self.documents))
        ])
        normalized_bm25 = _minmax(bm25_scores)

        matches = []
        for index, document in enumerate(self.documents):
            hybrid_score = (
                0.42 * normalized_vector[index]
                + 0.43 * normalized_bm25[index]
                + 0.15 * overlap_scores[index]
            )
            document = dict(self.documents[index])
            document["score"] = float(max(0.0, min(1.0, hybrid_score)))
            document["raw_vector_score"] = vector_by_index.get(index, 0.0)
            document["bm25_score"] = bm25_scores[index]
            document["overlap_score"] = overlap_scores[index]
            document["relevance"] = _relevance_label(document["score"])
            matches.append(document)

        return sorted(matches, key=lambda item: item["score"], reverse=True)[:limit]

    def _build_lexical_index(self):
        tokenized = [
            tokenize_for_retrieval(self._retrieval_text(doc))
            for doc in self.documents
        ]
        self.doc_token_counts = [Counter(tokens) for tokens in tokenized]
        self.doc_lengths = [len(tokens) for tokens in tokenized]
        self.avg_doc_length = (
            sum(self.doc_lengths) / len(self.doc_lengths)
            if self.doc_lengths
            else 0.0
        )

        document_frequency = Counter()
        for tokens in tokenized:
            document_frequency.update(set(tokens))

        doc_count = len(self.documents)
        self.idf = {
            token: math.log(1 + (doc_count - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }

    def _bm25_score(self, query_tokens, index):
        if not query_tokens or not self.doc_token_counts:
            return 0.0

        counts = self.doc_token_counts[index]
        doc_length = self.doc_lengths[index] or 1
        avg_length = self.avg_doc_length or 1.0
        k1 = 1.4
        b = 0.72
        score = 0.0

        for token in set(query_tokens):
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            idf = self.idf.get(token, 0.0)
            denominator = frequency + k1 * (1 - b + b * doc_length / avg_length)
            score += idf * frequency * (k1 + 1) / denominator
        return score

    def _overlap_score(self, query_tokens, index):
        if not query_tokens or not self.doc_token_counts:
            return 0.0
        query_set = set(query_tokens)
        doc_set = set(self.doc_token_counts[index])
        if not query_set:
            return 0.0
        return len(query_set & doc_set) / len(query_set)

    def _retrieval_text(self, document):
        return document.get("retrieval_text") or document.get("text") or ""


def _minmax(values):
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [1.0 if value > 0 else 0.0 for value in values]
    return [(value - low) / (high - low) for value in values]


def _relevance_label(score):
    if score >= 0.72:
        return "高度相关"
    if score >= 0.48:
        return "较相关"
    if score >= 0.25:
        return "可参考"
    return "弱相关"
