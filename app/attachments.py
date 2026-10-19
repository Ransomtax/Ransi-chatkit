import os
import uuid

import asyncpg
from fastapi import HTTPException, status
from starlette.requests import Request

from chatkit.store import AttachmentStore, NotFoundError
from chatkit.types import (
    Attachment,
    AttachmentCreateParams,
    AttachmentUploadDescriptor,
    FileAttachment,
)


MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}


class AttachmentContentStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                dsn=self.database_url,
                min_size=1,
                max_size=5,
            )

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ransi_attachment_content (
                        attachment_id TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        content BYTEA NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def save(
        self,
        attachment_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ):
        await self.connect()

        await self.pool.execute(
            """
            INSERT INTO ransi_attachment_content
                (attachment_id, filename, content_type, content)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (attachment_id) DO UPDATE SET
                filename = EXCLUDED.filename,
                content_type = EXCLUDED.content_type,
                content = EXCLUDED.content
            """,
            attachment_id,
            filename,
            content_type,
            content,
        )

    async def load(self, attachment_id: str):
        await self.connect()

        row = await self.pool.fetchrow(
            """
            SELECT filename, content_type, content
            FROM ransi_attachment_content
            WHERE attachment_id = $1
            """,
            attachment_id,
        )

        return dict(row) if row else None

    async def delete(self, attachment_id: str):
        await self.connect()

        await self.pool.execute(
            """
            DELETE FROM ransi_attachment_content
            WHERE attachment_id = $1
            """,
            attachment_id,
        )


class PostgresAttachmentStore(AttachmentStore[dict]):
    def __init__(
        self,
        metadata_store,
        content_store: AttachmentContentStore,
    ):
        self.metadata_store = metadata_store
        self.content_store = content_store

    async def create_attachment(
        self,
        input: AttachmentCreateParams,
        context: dict,
    ) -> Attachment:
        if input.mime_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Tipo di file non consentito.",
            )

        if input.size <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Il file è vuoto.",
            )

        if input.size > MAX_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Dimensione massima: 10 MB.",
            )

        request = context.get("request")

        if not isinstance(request, Request):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Contesto HTTP non disponibile per l'upload.",
            )

        attachment_id = self.generate_attachment_id(
            input.mime_type,
            context,
        )

        upload_url = request.url_for(
            "upload_attachment",
            attachment_id=attachment_id,
        )

        attachment = FileAttachment(
            id=attachment_id,
            name=os.path.basename(input.name or "allegato"),
            mime_type=input.mime_type,
            upload_descriptor=AttachmentUploadDescriptor(
                url=upload_url,
                method="PUT",
            ),
        )

        # Importante: salvare i metadati prima che il frontend
        # invii il contenuto del file.
        await self.metadata_store.save_attachment(
            attachment,
            context,
        )

        return attachment

    async def write_file(
        self,
        attachment_id: str,
        content: bytes,
        context: dict,
    ) -> Attachment:
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Il file è vuoto.",
            )

        if len(content) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Dimensione massima: 10 MB.",
            )

        try:
            attachment = await self.metadata_store.load_attachment(
                attachment_id,
                context,
            )
        except NotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Allegato non trovato nei metadati.",
            ) from exc

        if attachment.upload_descriptor is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Il file risulta già caricato.",
            )

        if attachment.mime_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Tipo di file non consentito.",
            )

        await self.content_store.save(
            attachment_id=attachment.id,
            filename=attachment.name,
            content_type=attachment.mime_type,
            content=content,
        )

        completed_attachment = attachment.model_copy(
            update={"upload_descriptor": None}
        )

        await self.metadata_store.save_attachment(
            completed_attachment,
            context,
        )

        return completed_attachment

    async def read_file(
        self,
        attachment_id: str,
        context: dict,
    ):
        try:
            attachment = await self.metadata_store.load_attachment(
                attachment_id,
                context,
            )
        except NotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Allegato non trovato.",
            ) from exc

        stored_file = await self.content_store.load(attachment_id)

        if stored_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contenuto del file non disponibile.",
            )

        return attachment, stored_file["content"]

    async def delete_attachment(
        self,
        attachment_id: str,
        context: dict,
    ) -> None:
        await self.content_store.delete(attachment_id)
        await self.metadata_store.delete_attachment(
            attachment_id,
            context,
        )
