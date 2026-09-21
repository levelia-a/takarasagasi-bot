import asyncio
import os
import unittest
from unittest.mock import patch

from pymysql.err import IntegrityError

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.tables import TABLES_SQL
from repositories.settings_repository import SettingsRepository
from repositories.progress_repository import ProgressRepository
from services.admin_service import AdminService
from services.db_service import DbService
from services.progress_service import ProgressService
from services.schema_service import SchemaService
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
        TreasureService._active_users = set()
        TreasureService._active_users_lock = asyncio.Lock()
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
            for table in ("admin_logs", "unlock_notifications", "user_progress_events", "user_progress", "statistics", "settings"):
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

    async def test_progress_save_retry_does_not_double_count_or_skip_reward(self):
        user_id = 1545489116127559684
        await SettingsService.update(
            {"beginner_max": 3}, 1, "admin", "最大探索変更"
        )
        session = await TreasureService.create(user_id, "retry-test", "beginner")
        original_record = ProgressService.record_exploration
        calls = 0

        async def lose_response_after_commit(*args, **kwargs):
            nonlocal calls
            result = await original_record(*args, **kwargs)
            calls += 1
            if calls == 1:
                # DBのCOMMITは成功したが、Botが成功応答を受け取れなかった状況。
                raise RuntimeError("commit成功後に通信断")
            return result

        with patch.object(
            ProgressService, "record_exploration", side_effect=lose_response_after_commit
        ):
            with self.assertRaises(RuntimeError):
                await TreasureService.explore(session)
            self.assertEqual(session.exploration_count, 1)

            # 同じ探索IDを再送しても、永続化した冪等性キーにより二重加算しない。
            await TreasureService.explore(session)
            await TreasureService.explore(session)
            await TreasureService.explore(session)

        self.assertEqual(session.exploration_count, 3)
        self.assertEqual(session.success_count, 3)
        self.assertEqual(session.reward, 8000)
        self.assertEqual(session.result, "max_success")
        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 3)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT COUNT(*) AS count FROM user_progress_events WHERE user_id = %s",
                (user_id,),
            )
            self.assertEqual((await cursor.fetchone())["count"], 3)

    async def test_unlock_notification_uses_current_settings(self):
        user_id = 1545489116127559685
        await SettingsService.update(
            {"intermediate_unlock": 1}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "settings-test", "beginner")

        # 開始後に条件が1回→2回へ変わった場合、1回目では通知しない。
        await SettingsService.update(
            {"intermediate_unlock": 2}, 1, "admin", "解放条件変更"
        )
        await TreasureService.explore(session)
        self.assertIsNone(session.unlocked_difficulty)

        # 現在条件の2回目に到達した時点で通知対象になる。
        session = await TreasureService.create(user_id, "settings-test", "beginner")
        await TreasureService.explore(session)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

    async def test_final_result_failure_rolls_back_progress_with_statistics(self):
        user_id = 1545489116127559686
        await SettingsService.update(
            {"beginner_max": 1}, 1, "admin", "最大探索変更"
        )
        session = await TreasureService.create(user_id, "atomic-test", "beginner")
        with patch(
            "services.progress_service.ResultRepository.insert_statistics_record_if_session_id_not_exists",
            side_effect=RuntimeError("statistics save failed"),
        ):
            with self.assertRaises(RuntimeError):
                await TreasureService.explore(session)

        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 0)
        self.assertEqual(len(await AdminService.history()), 0)

        await TreasureService.explore(session)
        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 1)
        self.assertEqual(len(await AdminService.history()), 1)

    async def test_lowered_threshold_can_issue_unlock_notification(self):
        user_id = 1545489116127559687
        await SettingsService.update(
            {"intermediate_unlock": 20}, 1, "admin", "解放条件変更"
        )
        for _ in range(15):
            session = await TreasureService.create(user_id, "lower-test", "beginner")
            await TreasureService.explore(session)

        await SettingsService.update(
            {"intermediate_unlock": 10}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "lower-test", "beginner")
        await TreasureService.explore(session)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

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

    async def test_schema_validation_rejects_old_database_before_gameplay(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("DROP TABLE unlock_notifications")
            await cursor.execute("DROP TABLE user_progress_events")
            await cursor.execute("DROP TABLE user_progress")

        with self.assertRaisesRegex(RuntimeError, "不足テーブル"):
            await SchemaService.validate_required_tables()

    async def test_read_connection_uses_autocommit_without_transaction(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertTrue(connection.get_autocommit())
            rows = await SettingsRepository.get_all_settings(cursor)
            self.assertEqual(len(rows), 0)
            self.assertFalse(connection.get_transaction_status())
