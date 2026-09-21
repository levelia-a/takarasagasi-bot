import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from consts.treasure import DEFAULT_SETTINGS
from services.db_service import DbService
from services.progress_service import ProgressService
from services.settings_service import SettingsService
from services.treasure_service import TreasureService, TreasureStopped


class TreasureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values = DEFAULT_SETTINGS.copy()
        self.settings = AsyncMock()
        self.settings.get_all.side_effect = lambda: self.values.copy()
        self.settings.validate_settings = SettingsService.validate_settings
        self.results = AsyncMock()
        self.db = MagicMock()
        self.connection = (
            self.db.get_connection.return_value.__aenter__.return_value
        ) = MagicMock()
        self.cursor = self.connection.cursor.return_value.__aenter__.return_value = (
            AsyncMock()
        )
        self.connection.begin = AsyncMock()
        self.connection.commit = AsyncMock()
        self.connection.rollback = AsyncMock()
        self.roll = 1
        self.enterContext(
            patch.object(DbService, "get_connection", self.db.get_connection)
        )
        self.enterContext(patch.object(SettingsService, "_lock", asyncio.Lock()))
        self.enterContext(
            patch("services.treasure_service.SettingsService", self.settings)
        )
        self.enterContext(
            patch("services.treasure_service.ResultRepository", self.results)
        )
        # この単体テストでは進捗保存を分離し、宝探し本体の状態遷移だけを検証する。
        self.progress = self.enterContext(
            patch.object(
                ProgressService,
                "record_exploration",
                new=AsyncMock(return_value=None),
            )
        )
        self.enterContext(
            patch(
                "services.treasure_service.random.randint",
                side_effect=lambda low, high: self.roll,
            )
        )

    async def create(self):
        return await TreasureService.create(1545489116127559681, "テスト🌟", "beginner")

    async def test_success_and_retreat(self):
        session = await self.create()
        await TreasureService.explore(session)
        await TreasureService.explore(session)
        self.assertEqual(session.reward, 4000)
        self.results.insert_statistics_record_if_session_id_not_exists.assert_not_awaited()
        await TreasureService.retreat(session)
        self.assertEqual(session.result, "retreat")
        self.assertEqual(session.success_count, 2)
        self.results.insert_statistics_record_if_session_id_not_exists.assert_awaited_once()
        cursor, record = (
            self.results.insert_statistics_record_if_session_id_not_exists.call_args.args
        )
        self.assertIs(cursor, self.cursor)
        self.assertEqual(record["final_reward"], 4000)
        self.assertEqual(record["result"], "retreat")
        self.connection.begin.assert_not_awaited()

    async def test_failure_loses_all_reward(self):
        session = await self.create()
        await TreasureService.explore(session)
        self.roll = 61
        await TreasureService.explore(session)
        self.assertEqual(
            (session.reward, session.result, session.exploration_count),
            (0, "failure", 2),
        )
        self.assertEqual(session.success_count, 1)

    async def test_rate_boundary(self):
        self.roll = 60
        session = await self.create()
        await TreasureService.explore(session)
        self.assertIsNone(session.result)
        self.roll = 61
        await TreasureService.explore(session)
        self.assertEqual(session.result, "failure")

    async def test_maximum_one_finishes_on_first_success(self):
        self.values["beginner_max"] = 1
        session = await self.create()
        await TreasureService.explore(session)
        self.assertEqual((session.reward, session.result), (2000, "max_success"))

    async def test_settings_are_fixed_for_active_game(self):
        session = await self.create()
        self.values.update(
            beginner_rate=0, beginner_price=9000, test_mode="always_fail"
        )
        await TreasureService.explore(session)
        self.assertEqual(session.reward, 2000)
        self.assertFalse(session.is_test)

    async def test_games_keep_separate_state_and_locks(self):
        first = await self.create()
        second = await TreasureService.create(2, "別の参加者", "beginner")
        self.assertNotEqual(first.id, second.id)
        self.assertIsNot(first.lock, second.lock)
        await TreasureService.explore(first)
        await TreasureService.retreat(first)
        self.assertEqual((first.reward, first.result), (2000, "retreat"))
        self.assertEqual(
            (second.reward, second.exploration_count, second.result), (0, 0, None)
        )

    async def test_forced_test_modes(self):
        for mode, result in [
            ("always_success", "max_success"),
            ("always_fail", "failure"),
        ]:
            with self.subTest(mode=mode):
                self.values.update(test_mode=mode, beginner_max=1)
                session = await self.create()
                await TreasureService.explore(session)
                self.assertEqual(session.result, result)
                self.assertTrue(session.is_test)

    async def test_operation_off_blocks_start(self):
        self.values["operation"] = 0
        with self.assertRaises(TreasureStopped):
            await self.create()

    async def test_failed_save_retries_same_result_without_reroll(self):
        session = await self.create()
        self.roll = 100
        self.progress.side_effect = [
            RuntimeError("connection lost"),
            None,
        ]

        with self.assertRaises(RuntimeError):
            await TreasureService.explore(session)

        self.assertEqual((session.result, session.exploration_count), ("failure", 1))
        exploration_id = session.pending_exploration_id
        self.assertIsNotNone(exploration_id)

        # 再試行時に乱数を成功側へ変えても、保存済みの失敗結果を再抽選しない。
        self.roll = 1
        await TreasureService.explore(session)

        self.assertEqual((session.result, session.exploration_count), ("failure", 1))
        self.assertIsNone(session.pending_exploration_id)
        self.assertEqual(self.progress.await_count, 2)
        first = self.progress.await_args_list[0].args
        second = self.progress.await_args_list[1].args
        self.assertEqual(first[2], exploration_id)
        self.assertEqual(second[2], exploration_id)
        self.assertEqual(first[3]["result"], "failure")
        self.assertEqual(second[3]["result"], "failure")

    async def test_concurrent_end_operations_do_not_change_result(self):
        self.values["beginner_max"] = 1
        session = await self.create()
        await asyncio.gather(
            TreasureService.explore(session), TreasureService.retreat(session)
        )
        self.assertEqual(
            (session.result, session.exploration_count, session.reward),
            ("max_success", 1, 2000),
        )

    async def test_invalid_settings_do_not_write(self):
        repository = AsyncMock()
        repository.get_all_settings_for_update.return_value = []
        logs = AsyncMock()
        self.enterContext(
            patch("services.settings_service.SettingsRepository", repository)
        )
        self.enterContext(patch("services.settings_service.AdminLogRepository", logs))
        for values in (
            {"beginner_rate": 101},
            {"beginner_price": -1},
            {"beginner_max": 0},
            {"beginner_max": 216},
            {"beginner_max": 215},
            {"test_mode": "invalid"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await SettingsService.update(values, 123, "admin", "test")
        repository.upsert_setting_by_key.assert_not_awaited()
        logs.insert_admin_log.assert_not_awaited()
        self.connection.commit.assert_not_awaited()
        self.assertEqual(self.connection.rollback.await_count, 6)

    async def test_settings_read_applies_defaults_and_types_without_transaction(self):
        repository = AsyncMock()
        repository.get_all_settings.return_value = [
            {"key": "beginner_price", "value": "42"},
            {"key": "test_mode", "value": "always_fail"},
            {"key": "unknown_key", "value": "ignored"},
        ]
        self.enterContext(
            patch("services.settings_service.SettingsRepository", repository)
        )
        settings = await SettingsService.get_all()
        self.assertEqual(settings["beginner_price"], 42)
        self.assertEqual(settings["intermediate_price"], 5000)
        self.assertEqual(settings["test_mode"], "always_fail")
        self.assertNotIn("unknown_key", settings)
        self.assertEqual(DEFAULT_SETTINGS["beginner_price"], 1000)
        repository.get_all_settings.assert_awaited_once_with(self.cursor)
        self.connection.begin.assert_not_awaited()
        self.connection.commit.assert_not_awaited()

    async def test_settings_update_and_log_share_cursor_and_commit(self):
        repository = AsyncMock()
        repository.get_all_settings_for_update.return_value = []
        logs = AsyncMock()
        self.enterContext(
            patch("services.settings_service.SettingsRepository", repository)
        )
        self.enterContext(patch("services.settings_service.AdminLogRepository", logs))
        await SettingsService.update({"beginner_price": 123}, 1, "admin", "価格変更")
        repository.upsert_setting_by_key.assert_awaited_once_with(
            self.cursor, "beginner_price", "123"
        )
        self.assertIs(logs.insert_admin_log.call_args.args[0], self.cursor)
        self.connection.begin.assert_awaited_once()
        self.connection.commit.assert_awaited_once()
        self.connection.rollback.assert_not_awaited()
