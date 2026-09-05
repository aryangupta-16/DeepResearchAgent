"""Document processing pipeline (worker-side boundary).

Flow: load → parse → chunk → embed → persist chunks (+embeddings) → READY.

Responsibilities kept out of this class on purpose: HTTP concerns, research
orchestration, and LLM synthesis. Retrieval is a separate service.

Idempotency: chunk replacement is atomic per document and chunk indices are
deterministic, so re-delivered tasks rebuild the same state instead of
appending duplicates.
"""

from __future__ import annotations

import logging

from app.documents.enums import DocumentStatus
from app.documents.repository import DocumentChunkRepository
from app.documents.service import DocumentService
from app.infrastructure.database.models.document import DocumentChunk
from app.rag.chunking import chunk_pages
from app.tools.documents.parser import parse_document

logger = logging.getLogger(__name__)

#: Outcomes understood by the generic queue handler.
OUTCOME_COMPLETED = "completed"
OUTCOME_RETRY = "retry"
OUTCOME_FAILED = "failed"


class DocumentProcessingService:
    """Processes one uploaded document into searchable, embedded chunks."""

    def __init__(
        self,
        *,
        session_factory,
        object_store,
        embedding_provider,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ) -> None:
        self._session_factory = session_factory
        self._object_store = object_store
        self._embedding_provider = embedding_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def process(self, document_id, *, attempt: int = 1) -> str:
        """Process one document; returns ``completed`` / ``retry`` / ``failed``."""
        async with self._session_factory() as session:
            service = DocumentService(
                session, object_store=self._object_store
            )
            document = await service.get_document(document_id)

            # Idempotency: already-processed documents are not re-embedded.
            if document.status == DocumentStatus.READY.value:
                logger.info("Document %s already ready; skipping.", document_id)
                return OUTCOME_COMPLETED

            try:
                await service.set_status(document_id, DocumentStatus.PROCESSING)
                logger.info(
                    "Processing document %s (filename=%s, size=%dB, attempt=%d).",
                    document_id, document.filename, document.size_bytes, attempt,
                )

                data = await service.read_stored_file(document)
                parsed = parse_document(
                    data, content_type=document.content_type,
                    filename=document.filename,
                )
                drafts = chunk_pages(
                    parsed.pages,
                    chunk_size=self._chunk_size,
                    overlap=self._chunk_overlap,
                )
                if not drafts:
                    raise ValueError("Document produced no chunks.")

                if self._embedding_provider is None:
                    raise RuntimeError(
                        "No embedding provider configured. Set EMBEDDING_PROVIDER "
                        "(e.g. 'openai') to enable document processing."
                    )
                vectors = await self._embedding_provider.embed_texts(
                    [draft.content for draft in drafts]
                )

                chunks = [
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=draft.chunk_index,
                        content=draft.content,
                        page_number=draft.page_number,
                        metadata_json={
                            "document_name": document.filename,
                            "content_type": document.content_type,
                        },
                        embedding=vector,
                    )
                    for draft, vector in zip(drafts, vectors, strict=True)
                ]
                await DocumentChunkRepository(session).replace_for_document(
                    document_id, chunks
                )
                await service.set_status(document_id, DocumentStatus.READY)

                logger.info(
                    "Document %s processed: %d page(s) -> %d chunk(s).",
                    document_id, len(parsed.pages), len(chunks),
                )
                return OUTCOME_COMPLETED

            except ValueError as exc:
                # Permanent: invalid/corrupt/unsupported documents never retry.
                logger.warning("Document %s failed permanently: %s", document_id, exc)
                await service.set_status(
                    document_id, DocumentStatus.FAILED, error=str(exc)
                )
                return OUTCOME_FAILED
            except Exception as exc:
                # Transient (network/storage/embedding provider): bounded retries.
                will_retry = attempt < 3
                logger.warning(
                    "Document %s processing failed (attempt=%d, retry=%s): %s",
                    document_id, attempt, will_retry, exc,
                )
                if will_retry:
                    # Back to pending so the reclaim sweep can also pick it up.
                    document.status = DocumentStatus.PENDING.value
                    document.error = str(exc)
                    await session.commit()
                    return OUTCOME_RETRY
                await service.set_status(
                    document_id, DocumentStatus.FAILED, error=str(exc)
                )
                return OUTCOME_FAILED