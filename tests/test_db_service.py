import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import DatabaseConfig
from services.db_service import DbService


class DbServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = DatabaseConfig("localhost", 3306, "test", "", "takara_test")
        self.enterContext(patch.object(DbService, "_pool", None))
        self.pool = MagicMock()
        self.pool.wait_closed = AsyncMock()
        self.create_pool = self.enterContext(
            patch("services.db_service.aiomysql.create_pool", new_callable=AsyncMock)
        )
        self.create_pool.return_value = self.pool

    async def test_shared_pool_is_closed_once_and_can_reconnect(self):
        await DbService.connect(self.config)
        with self.assertRaises(RuntimeError):
            await DbService.connect(self.config)
        self.create_pool.assert_awaited_once()
        first_context, second_context = MagicMock(), MagicMock()
        self.pool.acquire.side_effect = [first_context, second_context]
        async with (
            DbService.get_connection() as first,
            DbService.get_connection() as second,
        ):
            self.assertIs(first, first_context.__aenter__.return_value)
            self.assertIs(second, second_context.__aenter__.return_value)
        self.assertEqual(self.pool.acquire.call_count, 2)
        await DbService.close()
        await DbService.close()
        self.pool.close.assert_called_once()
        self.pool.wait_closed.assert_awaited_once()
        self.assertIsNone(DbService._pool)
        await DbService.connect(self.config)
        self.assertEqual(self.create_pool.await_count, 2)
        await DbService.close()

    async def test_connection_requires_open_pool(self):
        with self.assertRaises(RuntimeError):
            async with DbService.get_connection():
                self.fail("未接続のプールからは接続を取得できない")
        await DbService.connect(self.config)
        await DbService.close()
        with self.assertRaises(RuntimeError):
            async with DbService.get_connection():
                self.fail("終了後のプールからは接続を取得できない")

    async def test_connection_is_released_when_operation_fails(self):
        await DbService.connect(self.config)
        with self.assertRaisesRegex(ValueError, "test failure"):
            async with DbService.get_connection():
                raise ValueError("test failure")
        context = self.pool.acquire.return_value
        context.__aexit__.assert_awaited_once()
        self.assertIs(context.__aexit__.call_args.args[0], ValueError)
        await DbService.close()

    async def test_failed_connection_can_be_retried(self):
        self.create_pool.side_effect = [OSError("unavailable"), self.pool]
        with self.assertRaises(OSError):
            await DbService.connect(self.config)
        self.assertIsNone(DbService._pool)
        await DbService.connect(self.config)
        await DbService.close()
