"""Document ingestion API (Phase 8).

Uploads are asynchronous: ``POST`` persists the file + a ``pending`` document
row and enqueues processing — the binary is never parsed inside the request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.api.dependencies import get_document_service
from app.common.exceptions import NotFoundError
from app.documents.schemas import DocumentListResponse, DocumentResponse
from app.documents.service import DocumentService

router = APIRouter()

DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
UploadForm = Annotated[UploadFile, File()]


@router.post("", status_code=202, response_model=DocumentResponse)
async def upload_document(
    service: DocumentServiceDep,
    file: UploadForm,
) -> DocumentResponse:
    """Upload a document; persists metadata + binary, enqueues processing."""
    data = await file.read()
    document = await service.create_document(
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        data=data,
    )
    await service.enqueue_processing(document.id)  # outbox + Redis
    return DocumentResponse.model_validate(document)


@router.get("", response_model=DocumentListResponse)
async def list_documents(service: DocumentServiceDep) -> DocumentListResponse:
    documents = await service.list_documents()
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in documents],
        count=len(documents),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id, service: DocumentServiceDep) -> DocumentResponse:
    document = await service.get_document(document_id)
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
async def download_document(document_id, service: DocumentServiceDep) -> Response:
    """Stream the stored binary (used only by document sources)."""
    document = await service.get_document(document_id)
    try:
        content = await service.read_stored_file(document)
    except NotFoundError as exc:
        raise exc from exc
    return Response(
        content=content,
        media_type=document.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id, service: DocumentServiceDep) -> Response:
    """Hard-delete a document (204). 409 while processing, 404 when missing."""
    await service.delete_document(document_id)
    return Response(status_code=204)