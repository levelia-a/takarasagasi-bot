import os
import unittest
from unittest.mock import patch

from pymysql.err import IntegrityError

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.tables import TABLES_SQL
from repositories.admin_log_repository import AdminLogRepository
from repositories.connection import Database
from repositories.result_repository import ResultRepository
from repositories.settings_repository import SettingsRepository
from services.settings_service import SettingsService
from services.treasure_service import TreasureService


@unittest.skipUnless(
    os.getenv("TAKARA_TEST_MYSQL_URL"), "使い捨てMySQLのURLが未指定です"
)
class MySQLTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.dict(os.environ, {"MYSQL_URL": os.environ["TAKARA_TEST_MYSQL_URL"]}):
            self.database = Database(DatabaseConfig.from_env())
        await self.database.connect()
        self.addAsyncCleanup(self.database.close)
        # 既存DBを破壊しない。テスト用の空DBだけを受け付ける。
        async with self.database.transaction() as cursor:
            await cursor.execute("SHOW TABLES")
            if await cursor.fetchall():
                self.fail(
                    "MySQL結合テストには空の専用DBを指定してください。既存テーブルは削除しません。"
                )
        self.addAsyncCleanup(self.remove_created_tables)
        # テスト用DBにだけ、手動実行と同じSQLでテーブルを用意する。
        async with self.database.transaction() as cursor:
            for statement in TABLES_SQL.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        self.settings = SettingsRepository(self.database)
        self.results = ResultRepository(self.database)
        self.logs = AdminLogRepository(self.database)

    async def remove_created_tables(self):
        async with self.database.transaction() as cursor:
            for table in ("admin_logs", "statistics", "settings"):
                await cursor.execute(f"DROP TABLE IF EXISTS {table}")

    async def test_game_save_statistics_and_test_cleanup(self):
        settings = SettingsService(self.settings)
        await settings.update(
            {"beginner_price": 1234}, 1545489116127559681, "管理者🌟", "価格変更"
        )
        self.assertEqual((await self.settings.get_all())["beginner_price"], 1234)
        service = TreasureService(self.settings, self.results, lambda low, high: 1)
        session = await service.create(1545489116127559682, "参加者🌟", "beginner")
        await service.explore(session)
        await service.retreat(session)
        await self.results.save(session)
        rows = await self.results.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], 1545489116127559682)
        self.assertEqual(rows[0]["user_name"], "参加者🌟")
        self.assertEqual(rows[0]["final_reward"], 2468)
        await settings.update({"test_mode": "always_fail"}, 1, "admin", "テスト変更")
        test_session = await service.create(2, "test", "advanced")
        await service.explore(test_session)
        summary = await self.results.summary()
        self.assertEqual(
            (summary["total"], summary["consumed"], summary["payout"]), (1, 1234, 2468)
        )
        self.assertEqual(await self.results.delete_test_with_log(1, "admin"), 1)
        self.assertEqual(len(await self.results.recent()), 1)
        self.assertEqual(len(await self.logs.recent()), 3)

    async def test_setting_and_log_rollback_together(self):
        with self.assertRaises(IntegrityError):
            await self.settings.update_with_log(
                {"beginner_price": 99}, None, "admin", "test", "bad admin id"
            )
        self.assertEqual((await self.settings.get_all())["beginner_price"], 1000)
        self.assertEqual(await self.logs.recent(), ())

    async def test_empty_settings_use_defaults_without_inserting_rows(self):
        self.assertEqual(await self.settings.get_all(), DEFAULT_SETTINGS)
        async with self.database.transaction() as cursor:
            await cursor.execute("SELECT COUNT(*) AS count FROM settings")
            self.assertEqual((await cursor.fetchone())["count"], 0)
