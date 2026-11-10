import hashlib
import os
from typing import Protocol

from langchain_core.documents import Document


class SourceRetriever(Protocol):
    def search(self, query: str, *, k: int = 5) -> list[Document]: ...


class ApprovedPineconeRetriever:
    """Lazy Pinecone retrieval restricted to explicitly reviewed DE sources."""

    def __init__(
        self,
        *,
        api_key: str | None,
        index_name: str | None,
    ) -> None:
        self._api_key = api_key
        self._index_name = index_name
        self._store = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._index_name)

    def search(self, query: str, *, k: int = 5) -> list[Document]:
        store = self._get_store()
        documents = store.similarity_search(
            query,
            k=k,
            filter={
                "approved": True,
                "review_status": "approved",
                "jurisdiction": "DE",
            },
        )
        return [
            document
            for document in documents
            if document.metadata.get("approved") is True
            and document.metadata.get("review_status") == "approved"
            and document.metadata.get("jurisdiction") == "DE"
            and document.metadata.get("source_id")
            and document.metadata.get("source_version")
        ]

    def _get_store(self):
        if not self.configured:
            raise RuntimeError("Pinecone retrieval requires PINECONE_API_KEY and PINECONE_INDEX_NAME.")
        if self._store is None:
            from langchain_pinecone import PineconeVectorStore

            from src.helper import download_hugging_face_embeddings

            self._store = PineconeVectorStore(
                index_name=self._index_name,
                embedding=download_hugging_face_embeddings(),
                pinecone_api_key=self._api_key,
            )
        return self._store


class MedicalBookPineconeRetriever(ApprovedPineconeRetriever):
    """Read a configured book as reference material, without clinical approval."""

    def __init__(self, *, api_key: str | None, index_name: str | None, source: str) -> None:
        super().__init__(api_key=api_key, index_name=index_name)
        if not source.strip():
            raise ValueError("PINECONE_BOOK_SOURCE must identify the indexed book.")
        self._source = source

    def search(self, query: str, *, k: int = 5) -> list[Document]:
        documents = self._get_store().similarity_search(
            query, k=k, filter={"source": {"$eq": self._source}},
        )
        results = []
        for document in documents:
            if document.metadata.get("source") != self._source or not document.page_content.strip():
                continue
            chunk_id = hashlib.sha256(document.page_content.encode("utf-8")).hexdigest()[:12]
            title = self._source.replace("\\", "/").rsplit("/", 1)[-1]
            results.append(Document(page_content=document.page_content, metadata={
                **document.metadata,
                "source_id": f"BOOK-{chunk_id}",
                "source_version": "unversioned",
                "title": title,
                "chunk_id": chunk_id,
                "source_type": "medical_book_reference",
                "review_status": "unreviewed",
                "approved": False,
            }))
        return results


def create_pinecone_retriever(
    *,
    api_key: str | None = None,
    index_name: str | None = None,
    mode: str | None = None,
    source: str | None = None,
) -> ApprovedPineconeRetriever:
    options = dict(
        api_key=api_key if api_key is not None else os.getenv("PINECONE_API_KEY"),
        index_name=index_name if index_name is not None else os.getenv("PINECONE_INDEX_NAME"),
    )
    mode = mode if mode is not None else os.getenv("PINECONE_RETRIEVAL_MODE", "approved_sources")
    if mode == "medical_book":
        return MedicalBookPineconeRetriever(
            **options,
            source=source if source is not None else os.getenv("PINECONE_BOOK_SOURCE", "data\\Medical_book.pdf"),
        )
    if mode != "approved_sources":
        raise ValueError("PINECONE_RETRIEVAL_MODE must be approved_sources or medical_book.")
    return ApprovedPineconeRetriever(**options)
