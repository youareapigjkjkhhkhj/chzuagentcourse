import hashlib
import re

import numpy as np


_ASCII_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+\-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
}


def tokenize_for_retrieval(text):
    text = (text or "").lower()
    words = [
        token
        for token in _ASCII_TOKEN_RE.findall(text)
        if token not in _STOP_WORDS
    ]
    word_bigrams = [
        f"{words[index]}_{words[index + 1]}"
        for index in range(max(len(words) - 1, 0))
    ]
    cjk_chars = _CJK_RE.findall(text)
    cjk_bigrams = [
        "".join(cjk_chars[index:index + 2])
        for index in range(max(len(cjk_chars) - 1, 0))
    ]
    return words + word_bigrams + cjk_chars + cjk_bigrams


class HashingEmbeddingModel:
    """Small local embedding model for dependency-free retrieval.

    It uses signed feature hashing over English tokens and Chinese character
    bigrams. This is not a semantic embedding model, but it is reliable,
    deterministic, and good enough to make local RAG useful without an external
    embedding API.
    """

    def __init__(self, dimension=512):
        self.dimension = dimension

    def embed_documents(self, texts):
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.vstack([self.embed_query(text) for text in texts]).astype("float32")

    def embed_query(self, text):
        vector = np.zeros(self.dimension, dtype="float32")
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little", signed=False)
            index = value % self.dimension
            sign = 1.0 if (value >> 63) == 0 else -1.0
            vector[index] += sign

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def _tokens(self, text):
        return tokenize_for_retrieval(text)
