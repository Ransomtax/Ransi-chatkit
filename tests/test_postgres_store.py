```python
import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
```
