"""Retrieval over regulatory/knowledge docs (RBI circulars, SEBI, Income-tax Act, GST notifications, bank policies,
company filings). Dense (sentence-transformers+FAISS) when available, TF-IDF fallback. Every chunk keeps source+date
so answers can cite and stale rules can be flagged."""
from __future__ import annotations
import glob, os
import numpy as np

def chunk(text: str, size=900, overlap=150):
    i = 0
    while i < len(text):
        yield text[i:i + size]
        i += size - overlap

class Store:
    def __init__(self, dense: bool = True):
        self.docs: list[dict] = []
        self.dense = dense
        self._emb = None; self._index = None; self._tfidf = None; self._mat = None

    def add_dir(self, path: str, patterns=("*.txt", "*.md")):
        for pat in patterns:
            for fp in glob.glob(os.path.join(path, "**", pat), recursive=True):
                txt = open(fp, encoding="utf-8", errors="ignore").read()
                for c in chunk(txt):
                    self.docs.append({"text": c, "source": os.path.relpath(fp, path), "mtime": os.path.getmtime(fp)})

    def add_texts(self, items: list[tuple[str, str]]):
        for src, t in items:
            for c in chunk(t):
                self.docs.append({"text": c, "source": src, "mtime": 0})

    def build(self):
        texts = [d["text"] for d in self.docs]
        if self.dense:
            try:
                from sentence_transformers import SentenceTransformer
                import faiss
                self._emb = SentenceTransformer("BAAI/bge-m3")      # multilingual: English/Hindi/Telugu
                v = self._emb.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype("float32")
                self._index = faiss.IndexFlatIP(v.shape[1]); self._index.add(v)
                return
            except Exception as e:
                print(f"[rag] dense unavailable ({e}); using TF-IDF")
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(texts)
        self._mat = self._tfidf.transform(texts)

    def search(self, q: str, k=5) -> list[dict]:
        if self._index is not None:
            v = self._emb.encode([q], normalize_embeddings=True).astype("float32")
            s, i = self._index.search(v, k)
            return [{**self.docs[j], "score": float(sc)} for sc, j in zip(s[0], i[0]) if j >= 0]
        qv = self._tfidf.transform([q])
        sc = (self._mat @ qv.T).toarray().ravel()
        idx = np.argsort(-sc)[:k]
        return [{**self.docs[j], "score": float(sc[j])} for j in idx if sc[j] > 0]
