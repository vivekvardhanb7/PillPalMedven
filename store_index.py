import hashlib
import os

from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from src.helper import (
    download_hugging_face_embeddings,
    filter_to_minimal_docs,
    load_pdf_file,
    text_split,
)
from src.documents import load_approved_source_manifest


def validate_staging_index_name(index_name: str) -> str:
    if not index_name.endswith("-staging"):
        raise ValueError(
            "Document ingestion is restricted to staging indexes. "
            "Set PINECONE_INDEX_NAME to a name ending in '-staging'."
        )
    return index_name


def main() -> None:
    load_dotenv()

    pinecone_api_key = os.getenv("PINECONE_API_KEY")
    if not pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is missing. Add it to your .env file.")

    index_name = validate_staging_index_name(
        os.getenv("PINECONE_INGEST_INDEX_NAME", "medical-chatbot-staging")
    )
    extracted_data = load_pdf_file(data="data/")
    if not extracted_data:
        raise RuntimeError("No PDF pages found under data/. Add a source PDF.")
    source_manifest = load_approved_source_manifest(
        os.getenv(
            "APPROVED_SOURCE_MANIFEST",
            "instance/approved_source_manifest.json",
        )
    )
    filtered_data = filter_to_minimal_docs(extracted_data, source_manifest)
    text_chunks = text_split(filtered_data)
    if not text_chunks:
        raise RuntimeError("PDF extraction produced no text chunks; check the source files.")

    pinecone = Pinecone(api_key=pinecone_api_key)
    if not pinecone.has_index(index_name):
        pinecone.create_index(
            name=index_name,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    else:
        description = pinecone.describe_index(name=index_name)
        if description.dimension != 384 or description.metric != "cosine":
            raise RuntimeError(
                f"Staging index {index_name!r} must use 384 dimensions and cosine similarity."
            )

    embeddings = download_hugging_face_embeddings()
    chunk_ids = [
        hashlib.sha256(
            (
                f"{document.metadata.get('source', 'unknown')}|"
                f"{document.metadata.get('page', 0)}|{document.page_content}"
            ).encode("utf-8")
        ).hexdigest()
        for document in text_chunks
    ]
    for document, chunk_id in zip(text_chunks, chunk_ids):
        document.metadata["chunk_id"] = chunk_id

    PineconeVectorStore.from_documents(
        documents=text_chunks,
        index_name=index_name,
        embedding=embeddings,
        ids=chunk_ids,
    )


if __name__ == "__main__":
    main()
