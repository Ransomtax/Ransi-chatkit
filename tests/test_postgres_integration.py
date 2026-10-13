```python
import asyncio
import os
import unittest

from app.postgres_store import PostgresStore


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_INTEGRATION") == "1",
    "Test PostgreSQL reale disattivato",
)
class TestPostgresIntegration(unittest.TestCase):
    def test_read_existing_threads_and_items(self):
        async def run():
            store = PostgresStore()

            try:
                await store.connect()

                # Legge una conversazione esistente senza modificarla.
                async with store.pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT id
                        FROM ransi_threads
                        ORDER BY created_at ASC, id ASC
                        LIMIT 1
                    """)

                self.assertIsNotNone(
                    row,
                    "Non ci sono conversazioni da verificare.",
                )

                thread_id = row["id"]

                thread = await store.load_thread(thread_id, {})
                self.assertEqual(thread.id, thread_id)

                page = await store.load_thread_items(
                    thread_id=thread_id,
                    after=None,
                    limit=10,
                    order="asc",
                    context={},
                )

                self.assertIsNotNone(page.data)
                self.assertLessEqual(len(page.data), 10)

                # Verifica anche la lettura di ogni elemento restituito.
                for item in page.data:
                    loaded = await store.load_item(
                        thread_id,
                        item.id,
                        {},
                    )
                    self.assertEqual(loaded.id, item.id)

            finally:
                if store.pool is not None:
                    await store.pool.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
```
