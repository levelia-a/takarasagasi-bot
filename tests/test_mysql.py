import os
import unittest
from unittest.mock import patch

from pymysql.err import IntegrityError

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.tables import TABLES_SQL
from repositories.admin_log_repository import AdminLogRepository
from repositories.result_repository import ResultRepository
from repositories.settings_repository import SettingsRepository
from services.admin_service import AdminService
from services.db_service import DbService
from services.settings_service import SettingsService
from services.treasure_service import TreasureService


@unittest.skipUnless(
    os.getenv("TAKARA_TEST_MYSQL_URL"), "使い捨てMySQLのURLが未指定です"
)
class MySQLTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.dict(os.environ, {"MYSQL_URL": os.environ["TAKARA_TEST_MYSQL_URL"]}):
            self.db = DbService(DatabaseConfig.from_env())
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        # 既存DBを破壊しない。テスト用の空DBだけを受け付ける。
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SHOW TABLES")
            if await cursor.fetchall():
                self.fail(
                    "MySQL結合テストには空の専用DBを指定してください。既存テーブルは削除しません。"
                )
        self.addAsyncCleanup(self.remove_created_tables)
        # テスト用DBにだけ、手動実行と同じSQLでテーブルを用意する。
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for statement in TABLES_SQL.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        self.settings_repository = SettingsRepository()
        self.results = ResultRepository()
        self.logs = AdminLogRepository()
        self.settings = SettingsService(self.db, self.settings_repository, self.logs)
        self.admin = AdminService(self.db, self.results, self.logs)

    async def remove_created_tables(self):
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for table in ("admin_logs", "statistics", "settings"):
                await cursor.execute(f"DROP TABLE IF EXISTS {table}")

    async def test_game_save_statistics_and_test_cleanup(self):
        settings = self.settings
        await settings.update(
            {"beginner_price": 1234}, 1545489116127559681, "管理者🌟", "価格変更"
        )
        self.assertEqual((await self.settings.get_all())["beginner_price"], 1234)
        service = TreasureService(
            self.db, self.settings, self.results, lambda low, high: 1
        )
        session = await service.create(1545489116127559682, "参加者🌟", "beginner")
        await service.explore(session)
        await service.retreat(session)
        await service.save_result(session)
        rows = await self.admin.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], 1545489116127559682)
        self.assertEqual(rows[0]["user_name"], "参加者🌟")
        self.assertEqual(rows[0]["final_reward"], 2468)
        await settings.update({"test_mode": "always_fail"}, 1, "admin", "テスト変更")
        test_session = await service.create(2, "test", "advanced")
        await service.explore(test_session)
        summary = await self.admin.statistics()
        self.assertEqual(
            (summary["total"], summary["consumed"], summary["payout"]), (1, 1234, 2468)
        )
        self.assertEqual(await self.admin.delete_test(1, "admin"), 1)
        self.assertEqual(len(await self.admin.history()), 1)
        self.assertEqual(len(await self.admin.admin_logs()), 3)

    async def test_setting_and_log_rollback_together(self):
        with self.assertRaises(IntegrityError):
            await self.settings.update({"beginner_price": 99}, None, "admin", "test")
        self.assertEqual((await self.settings.get_all())["beginner_price"], 1000)
        self.assertEqual(await self.admin.admin_logs(), ())

    async def test_empty_settings_use_defaults_without_inserting_rows(self):
        self.assertEqual(await self.settings.get_all(), DEFAULT_SETTINGS)
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT COUNT(*) AS count FROM settings")
            self.assertEqual((await cursor.fetchone())["count"], 0)

    async def test_test_history_deletion_rolls_back_when_log_fails(self):
        await self.settings.update({"test_mode": "always_fail"}, 1, "admin", "test")
        service = TreasureService(self.db, self.settings, self.results)
        session = await service.create(2, "test", "beginner")
        await service.explore(session)
        with self.assertRaises(IntegrityError):
            await self.admin.delete_test(None, "admin")
        self.assertEqual(len(await self.admin.history()), 1)
        self.assertEqual(len(await self.admin.admin_logs()), 1)

    async def test_operation_toggle_is_saved_with_log(self):
        self.assertEqual(await self.settings.toggle_operation(1, "admin"), 0)
        self.assertEqual(await self.settings.toggle_operation(1, "admin"), 1)
        self.assertEqual((await self.settings.get_all())["operation"], 1)
        self.assertEqual(len(await self.admin.admin_logs()), 2)

    async def test_read_connection_uses_autocommit_without_transaction(self):
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertTrue(connection.get_autocommit())
            rows = await self.settings_repository.get_all_settings(cursor)
            self.assertEqual(len(rows), 0)
            self.assertFalse(connection.get_transaction_status())
