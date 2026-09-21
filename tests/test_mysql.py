import asyncio
import os
import unittest
from unittest.mock import patch

from pymysql.err import IntegrityError

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.tables import TABLES_SQL
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
            config = DatabaseConfig.from_env()
        await DbService.connect(config)
        self.addAsyncCleanup(DbService.close)
        # 既存DBを破壊しない。テスト用の空DBだけを受け付ける。
        async with (
            DbService.get_connection() as connection,
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
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for statement in TABLES_SQL.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        self.enterContext(patch.object(SettingsService, "_lock", asyncio.Lock()))
        self.enterContext(
            patch("services.treasure_service.random.randint", return_value=1)
        )

    async def remove_created_tables(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for table in ("admin_logs", "user_progress", "statistics", "settings"):
                await cursor.execute(f"DROP TABLE IF EXISTS {table}")

    async def test_game_save_statistics_and_test_cleanup(self):
        await SettingsService.update(
            {"beginner_price": 1234}, 1545489116127559681, "管理者🌟", "価格変更"
        )
        self.assertEqual((await SettingsService.get_all())["beginner_price"], 1234)
        session = await TreasureService.create(
            1545489116127559682, "参加者🌟", "beginner"
        )
        await TreasureService.explore(session)
        await TreasureService.retreat(session)
        await TreasureService.save_result(session)
        rows = await AdminService.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], 1545489116127559682)
        self.assertEqual(rows[0]["user_name"], "参加者🌟")
        self.assertEqual(rows[0]["final_reward"], 2468)
        await SettingsService.update(
            {"test_mode": "always_fail"}, 1, "admin", "テスト変更"
        )
        # テストモードは解放進捗を増やさないが、未解放難易度の開始制限は有効。
        test_session = await TreasureService.create(2, "test", "beginner")
        await TreasureService.explore(test_session)
        summary = await AdminService.statistics()
        self.assertEqual(
            (summary["total"], summary["consumed"], summary["payout"]), (1, 1234, 2468)
        )
        self.assertEqual(await AdminService.delete_test(1, "admin"), 1)
        self.assertEqual(len(await AdminService.history()), 1)
        self.assertEqual(len(await AdminService.admin_logs()), 3)

    async def test_difficulty_unlock_is_based_on_current_exploration_count(self):
        user_id = 1545489116127559683
        await SettingsService.update(
            {"intermediate_unlock": 1}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "unlock-test", "beginner")
        await TreasureService.explore(session)

        # 初級探索1回・条件1回なら中級に挑戦できる。
        unlocked = await TreasureService.create(user_id, "unlock-test", "intermediate")
        self.assertEqual(unlocked.difficulty, "intermediate")

        # 条件を2回へ引き上げると、探索回数1回では再び未達になる。
        await SettingsService.update(
            {"intermediate_unlock": 2}, 1, "admin", "解放条件変更"
        )
        with self.assertRaises(ValueError):
            await TreasureService.create(user_id, "unlock-test", "intermediate")

        # 初級をもう1回探索して合計2回になれば、再び中級に挑戦できる。
        session = await TreasureService.create(user_id, "unlock-test", "beginner")
        await TreasureService.explore(session)
        unlocked = await TreasureService.create(user_id, "unlock-test", "intermediate")
        self.assertEqual(unlocked.difficulty, "intermediate")

    async def test_test_mode_does_not_increment_unlock_progress(self):
        await SettingsService.update(
            {"test_mode": "always_success", "intermediate_unlock": 1},
            1,
            "admin",
            "テスト変更",
        )
        session = await TreasureService.create(999, "test", "beginner")
        await TreasureService.explore(session)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT beginner_explorations FROM user_progress WHERE user_id = %s",
                (999,),
            )
            self.assertIsNone(await cursor.fetchone())

    async def test_setting_and_log_rollback_together(self):
        with self.assertRaises(IntegrityError):
            await SettingsService.update({"beginner_price": 99}, None, "admin", "test")
        self.assertEqual((await SettingsService.get_all())["beginner_price"], 1000)
        self.assertEqual(await AdminService.admin_logs(), ())

    async def test_empty_settings_use_defaults_without_inserting_rows(self):
        self.assertEqual(await SettingsService.get_all(), DEFAULT_SETTINGS)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT COUNT(*) AS count FROM settings")
            self.assertEqual((await cursor.fetchone())["count"], 0)

    async def test_test_history_deletion_rolls_back_when_log_fails(self):
        await SettingsService.update({"test_mode": "always_fail"}, 1, "admin", "test")
        session = await TreasureService.create(2, "test", "beginner")
        await TreasureService.explore(session)
        with self.assertRaises(IntegrityError):
            await AdminService.delete_test(None, "admin")
        self.assertEqual(len(await AdminService.history()), 1)
        self.assertEqual(len(await AdminService.admin_logs()), 1)

    async def test_operation_toggle_is_saved_with_log(self):
        self.assertEqual(await SettingsService.toggle_operation(1, "admin"), 0)
        self.assertEqual(await SettingsService.toggle_operation(1, "admin"), 1)
        self.assertEqual((await SettingsService.get_all())["operation"], 1)
        self.assertEqual(len(await AdminService.admin_logs()), 2)

    async def test_concurrent_toggles_share_lock_and_preserve_all_changes(self):
        states = await asyncio.gather(
            *(SettingsService.toggle_operation(1, "admin") for _ in range(8))
        )
        self.assertEqual(states, [0, 1] * 4)
        self.assertEqual((await SettingsService.get_all())["operation"], 1)
        self.assertEqual(len(await AdminService.admin_logs()), 8)

    async def test_read_connection_uses_autocommit_without_transaction(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertTrue(connection.get_autocommit())
            rows = await SettingsRepository.get_all_settings(cursor)
            self.assertEqual(len(rows), 0)
            self.assertFalse(connection.get_transaction_status())
