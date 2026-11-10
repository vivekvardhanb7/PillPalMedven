import json
from pathlib import Path
from typing import List
from typing import Literal

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, ValidationError


class ApprovedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str
    source_id: str
    source_version: str
    approved: bool
    review_status: Literal["unreviewed", "approved", "withdrawn"]
    approved_by: str | None = None
    jurisdiction: Literal["DE"]
    language: Literal["en", "de"]


def load_approved_source_manifest(path: str | Path) -> dict[str, ApprovedSource]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    try:
        records = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Unable to load source-review manifest from {manifest_path}.") from error
    if not isinstance(records, list):
        raise ValueError("The source-review manifest must contain a JSON array.")
    manifest: dict[str, ApprovedSource] = {}
    for record in records:
        try:
            source = ApprovedSource.model_validate(record)
        except ValidationError as error:
            raise ValueError("The source-review manifest contains an invalid entry.") from error
        key = Path(source.source_file).name.casefold()
        if key in manifest:
            raise ValueError(f"The source-review manifest duplicates {source.source_file!r}.")
        if source.approved and (
            source.review_status != "approved"
            or not source.approved_by
            or not source.source_version.strip()
            or not source.source_id.strip()
        ):
            raise ValueError(
                f"Approved source {source.source_file!r} requires reviewer, source ID, "
                "version, and approved status."
            )
        manifest[key] = source
    return manifest


def filter_to_minimal_docs(
    docs: List[Document],
    approved_source_manifest: dict[str, ApprovedSource] | None = None,
) -> List[Document]:
    """Keep source provenance; unreviewed documents remain explicitly unapproved."""
    minimal_docs: List[Document] = []
    for doc in docs:
        src = doc.metadata.get("source")
        file_name = Path(src).name if src else "unknown"
        approval = (approved_source_manifest or {}).get(file_name.casefold())
        metadata = {
            "source": file_name,
            "page": int(doc.metadata.get("page", 0)),
            "jurisdiction": approval.jurisdiction if approval else "DE",
            "language": approval.language if approval else "unknown",
            "source_version": approval.source_version if approval else "unreviewed",
            "source_id": approval.source_id if approval else "unreviewed",
            "review_status": (
                approval.review_status if approval else "unreviewed"
            ),
            "approved": bool(approval and approval.approved),
        }
        if approval and approval.approved and approval.approved_by:
            metadata["approved_by"] = approval.approved_by
        minimal_docs.append(
            Document(
                page_content=doc.page_content,
                metadata=metadata,
            )
        )
    return minimal_docs
