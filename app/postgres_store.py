import json
import os
from uuid import uuid4

import asyncpg
from pydantic import TypeAdapter

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, ThreadItem, ThreadMetadata


THREAD_ITEM_ADAPTER = TypeAdapter(ThreadItem)


def decode_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


class PostgresStore(Store[dict]):
    def __init__(self):
        self.pool = None

    async def connect(self):
        if self.pool is not None:
            return

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL non configurata")

        pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=5,
        )

        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ransi_threads (
                        id TEXT PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        data JSONB NOT NULL
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ransi_thread_items (
                        id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL
                            REFERENCES ransi_threads(id)
                            ON DELETE CASCADE,
                        created_at TIMESTAMPTZ NOT NULL,
                        data JSONB NOT NULL
                    )
                """)

                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS
                    ransi_thread_items_thread_created_idx
                    ON ransi_thread_items(thread_id, created_at, id)
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ransi_attachments (
                        id TEXT PRIMARY KEY,
                        data JSONB NOT NULL
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ransi_agent_sessions (
                        thread_id TEXT PRIMARY KEY
                            REFERENCES ransi_threads(id)
                            ON DELETE CASCADE,
                        session_id TEXT NOT NULL
                    )
                """)

        except Exception:
            await pool.close()
            raise

        self.pool = pool

    def generate_thread_id(self, context):
        return f"thread_{uuid4().hex}"

    async def load_thread(self, thread_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM ransi_threads WHERE id = $1",
                thread_id,
            )

        if row is None:
            raise NotFoundError(f"Thread {thread_id} not found")

        return ThreadMetadata.model_validate(decode_json(row["data"]))

    async def save_thread(self, thread, context):
        await self.connect()
        data = json.dumps(thread.model_dump(mode="json"))

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO ransi_threads (id, created_at, data)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (id) DO UPDATE
                SET created_at = EXCLUDED.created_at,
                    data = EXCLUDED.data
            """, thread.id, thread.created_at, data)

    async def load_threads(self, limit, after, order, context):
        await self.connect()
        direction = "DESC" if order == "desc" else "ASC"
        operator = "<" if direction == "DESC" else ">"

        async with self.pool.acquire() as conn:
            if after:
                cursor = await conn.fetchrow("""
                    SELECT created_at
                    FROM ransi_threads
                    WHERE id = $1
                """, after)

                if cursor is None:
                    return Page(data=[], has_more=False, after=None)

                rows = await conn.fetch(
                    f"""
                    SELECT data, id
                    FROM ransi_threads
                    WHERE (created_at, id) {operator} ($1, $2)
                    ORDER BY created_at {direction}, id {direction}
                    LIMIT $3
                    """,
                    cursor["created_at"],
                    after,
                    limit + 1,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT data, id
                    FROM ransi_threads
                    ORDER BY created_at {direction}, id {direction}
                    LIMIT $1
                    """,
                    limit + 1,
                )

        has_more = len(rows) > limit
        selected = rows[:limit]
        threads = [
            ThreadMetadata.model_validate(decode_json(row["data"]))
            for row in selected
        ]
        next_after = selected[-1]["id"] if has_more and selected else None

        return Page(
            data=threads,
            has_more=has_more,
            after=next_after,
        )

    async def load_thread_items(
        self, thread_id, after, limit, order, context
    ):
        await self.connect()
        direction = "DESC" if order == "desc" else "ASC"
        operator = "<" if direction == "DESC" else ">"

        async with self.pool.acquire() as conn:
            if after:
                cursor = await conn.fetchrow("""
                    SELECT created_at
                    FROM ransi_thread_items
                    WHERE thread_id = $1 AND id = $2
                """, thread_id, after)

                if cursor is None:
                    return Page(data=[], has_more=False, after=None)

                rows = await conn.fetch(
                    f"""
                    SELECT data, id
                    FROM ransi_thread_items
                    WHERE thread_id = $1
                      AND (created_at, id) {operator} ($2, $3)
                    ORDER BY created_at {direction}, id {direction}
                    LIMIT $4
                    """,
                    thread_id,
                    cursor["created_at"],
                    after,
                    limit + 1,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT data, id
                    FROM ransi_thread_items
                    WHERE thread_id = $1
                    ORDER BY created_at {direction}, id {direction}
                    LIMIT $2
                    """,
                    thread_id,
                    limit + 1,
                )

        has_more = len(rows) > limit
        selected = rows[:limit]
        items = [
            THREAD_ITEM_ADAPTER.validate_python(
                decode_json(row["data"])
            )
            for row in selected
        ]
        next_after = selected[-1]["id"] if has_more and selected else None

        return Page(
            data=items,
            has_more=has_more,
            after=next_after,
        )

    async def add_thread_item(self, thread_id, item, context):
        await self.save_item(thread_id, item, context)

    async def save_item(self, thread_id, item, context):
        await self.connect()
        data = json.dumps(item.model_dump(mode="json"))

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO ransi_thread_items
                    (id, thread_id, created_at, data)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    thread_id = EXCLUDED.thread_id,
                    created_at = EXCLUDED.created_at,
                    data = EXCLUDED.data
            """, item.id, thread_id, item.created_at, data)

    async def load_item(self, thread_id, item_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT data FROM ransi_thread_items
                WHERE thread_id = $1 AND id = $2
            """, thread_id, item_id)

        if row is None:
            raise NotFoundError(
                f"Item {item_id} not found in thread {thread_id}"
            )

        return THREAD_ITEM_ADAPTER.validate_python(
            decode_json(row["data"])
        )

    async def delete_thread(self, thread_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ransi_threads WHERE id = $1",
                thread_id,
            )

    async def delete_thread_item(self, thread_id, item_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM ransi_thread_items
                WHERE thread_id = $1 AND id = $2
            """, thread_id, item_id)

    async def save_attachment(self, attachment, context):
        await self.connect()
        data = json.dumps(attachment.model_dump(mode="json"))

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO ransi_attachments (id, data)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (id) DO UPDATE
                SET data = EXCLUDED.data
            """, attachment.id, data)

    async def load_attachment(self, attachment_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM ransi_attachments WHERE id = $1",
                attachment_id,
            )

        if row is None:
            raise NotFoundError(
                f"Attachment {attachment_id} not found"
            )

        return Attachment.model_validate(decode_json(row["data"]))

    async def delete_attachment(self, attachment_id, context):
        await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ransi_attachments WHERE id = $1",
                attachment_id,
            )

    async def get_agent_session_id(self, thread_id):
        await self.connect()

        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT session_id
                FROM ransi_agent_sessions
                WHERE thread_id = $1
            """, thread_id)

    async def save_agent_session_id(self, thread_id, session_id):
        await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO ransi_agent_sessions (thread_id, session_id)
                VALUES ($1, $2)
                ON CONFLICT (thread_id) DO UPDATE
                SET session_id = EXCLUDED.session_id
            """, thread_id, session_id)
