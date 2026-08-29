"""轻量本地向量检索与 RAG 适配层，无外部服务也可运行。"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Document:
    document_id: str
    text: str
    metadata: dict[str, Any]


class InMemoryVectorStore:
    def __init__(self, documents: list[Document] | None = None) -> None:
        self.documents = documents or []

    def add(self, document: Document) -> None:
        if not document.document_id or not document.text:
            raise ValueError("document_id 和 text 不能为空")
        self.documents.append(document)

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        if not query or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("query 不能为空，top_k 必须是正整数")
        query_terms = _terms(query)
        scored = []
        for document in self.documents:
            terms = _terms(document.text)
            score = sum(query_terms.count(term) * terms.count(term) for term in set(query_terms))
            scored.append((score, document))
        return [document for score, document in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k] if score > 0]

    def health_check(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须是正数")

    def close(self) -> None:
        return


class HttpVectorStore:
    """外部向量数据库的最小 HTTP 适配协议。"""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url 必须是 HTTP 地址")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        if not query or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("query 不能为空，top_k 必须是正整数")
        request = Request(
            f"{self.base_url}/search",
            data=json.dumps({"query": query, "top_k": top_k}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("向量库返回必须是数组")
        return [
            Document(str(item["document_id"]), str(item["text"]), dict(item.get("metadata", {})))
            for item in data
            if isinstance(item, dict) and item.get("document_id") and item.get("text")
        ]

    def health_check(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须是正数")

    def close(self) -> None:
        return


class RAGService:
    def __init__(self, store: InMemoryVectorStore, llm_client: Any | None = None) -> None:
        self.store = store
        self.llm_client = llm_client

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        return [{"document_id": doc.document_id, "text": doc.text, "metadata": doc.metadata} for doc in self.store.search(query, top_k)]

    def explain(self, query: str, context: Mapping[str, Any]) -> dict[str, Any]:
        docs = self.retrieve(query)
        result = {"documents": docs, "answer": ""}
        if self.llm_client is not None:
            result["answer"] = self.llm_client.generate("请只依据检索到的运维案例回答，并说明证据来源。", {"query": query, "documents": docs, "context": dict(context)})
        return result


def _terms(text: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[A-Za-z0-9_:-]+|[\u4e00-\u9fff]", text)]
