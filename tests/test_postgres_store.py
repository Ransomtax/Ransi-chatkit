import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.postgres_store import PostgresStore


class TestPostgresStore(unittest.IsolatedAsyncioTestCase):
    async def test_connect_requires_database_url(self):
        store = PostgresStore()

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "DATABASE_URL non configurata",
            ):
                await store.connect()

        self.assertIsNone(store.pool)

    async def test_generate_thread_id(self):
        store = PostgresStore()

        first_id = store.generate_thread_id({})
        second_id = store.generate_thread_id({})

        self.assertTrue(first_id.startswith("thread_"))
        self.assertNotEqual(first_id, second_id)

    async def test_load_threads_uses_cursor_and_limit(self):
        store = PostgresStore()
        store.connect = AsyncMock()

        timestamp = datetime.now(timezone.utc)

        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={"created_at": timestamp}
        )
        conn.fetch = AsyncMock(return_value=[])

        acquire_context = MagicMock()
        acquire_context.__aenter__ = AsyncMock(return_value=conn)
        acquire_context.__aexit__ = AsyncMock(return_value=False)

        pool = MagicMock()
        pool.acquire.return_value = acquire_context
        store.pool = pool

        page = await store.load_threads(
            limit=10,
            after="thread_cursor",
            order="asc",
            context={},
        )

        self.assertEqual(page.data, [])
        self.assertFalse(page.has_more)
        self.assertIsNone(page.after)
        conn.fetchrow.assert_awaited_once()
        conn.fetch.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
