import asyncpg


class AttachmentContentStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self.database_url)

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def save(self, attachment_id: str, filename: str, content_type: str, content: bytes):
        await self.connect()
        await self.pool.execute(
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
            "DELETE FROM ransi_attachment_content WHERE attachment_id = $1",
            attachment_id,
        )
