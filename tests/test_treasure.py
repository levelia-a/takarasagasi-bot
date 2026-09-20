import asyncio
import unittest
from unittest.mock import AsyncMock

from consts.treasure import DEFAULT_SETTINGS
from services.settings_service import SettingsService
from services.treasure_service import TreasureService, TreasureStopped


class TreasureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values = DEFAULT_SETTINGS.copy()
        self.settings = AsyncMock()
        self.settings.get_all.side_effect = lambda: self.values.copy()
        self.results = AsyncMock()
        self.roll = 1
        self.service = TreasureService(
            self.settings, self.results, lambda low, high: self.roll
        )

    async def create(self):
        return await self.service.create(1545489116127559681, "テスト🌟", "beginner")

    async def test_success_and_retreat(self):
        session = await self.create()
        await self.service.explore(session)
        await self.service.explore(session)
        self.assertEqual(session.reward, 4000)
        self.results.save.assert_not_awaited()
        await self.service.retreat(session)
        self.assertEqual(session.result, "retreat")
        self.assertEqual(session.success_count, 2)
        self.results.save.assert_awaited_once_with(session)

    async def test_failure_loses_all_reward(self):
        session = await self.create()
        await self.service.explore(session)
        self.roll = 61
        await self.service.explore(session)
        self.assertEqual(
            (session.reward, session.result, session.exploration_count),
            (0, "failure", 2),
        )
        self.assertEqual(session.success_count, 1)

    async def test_rate_boundary(self):
        self.roll = 60
        session = await self.create()
        await self.service.explore(session)
        self.assertIsNone(session.result)
        self.roll = 61
        await self.service.explore(session)
        self.assertEqual(session.result, "failure")

    async def test_maximum_one_finishes_on_first_success(self):
        self.values["beginner_max"] = 1
        session = await self.create()
        await self.service.explore(session)
        self.assertEqual((session.reward, session.result), (2000, "max_success"))

    async def test_settings_are_fixed_for_active_game(self):
        session = await self.create()
        self.values.update(
            beginner_rate=0, beginner_price=9000, test_mode="always_fail"
        )
        await self.service.explore(session)
        self.assertEqual(session.reward, 2000)
        self.assertFalse(session.is_test)

    async def test_forced_test_modes(self):
        for mode, result in [
            ("always_success", "max_success"),
            ("always_fail", "failure"),
        ]:
            with self.subTest(mode=mode):
                self.values.update(test_mode=mode, beginner_max=1)
                session = await self.create()
                await self.service.explore(session)
                self.assertEqual(session.result, result)
                self.assertTrue(session.is_test)

    async def test_operation_off_blocks_start(self):
        self.values["operation"] = 0
        with self.assertRaises(TreasureStopped):
            await self.create()

    async def test_failed_save_retries_same_result_without_reroll(self):
        session = await self.create()
        self.roll = 100
        self.results.save.side_effect = [RuntimeError("connection lost"), None]
        with self.assertRaises(RuntimeError):
            await self.service.explore(session)
        self.roll = 1
        await self.service.explore(session)
        self.assertEqual((session.result, session.exploration_count), ("failure", 1))

    async def test_concurrent_end_operations_do_not_change_result(self):
        self.values["beginner_max"] = 1
        session = await self.create()
        await asyncio.gather(
            self.service.explore(session), self.service.retreat(session)
        )
        self.assertEqual(
            (session.result, session.exploration_count, session.reward),
            ("max_success", 1, 2000),
        )

    async def test_invalid_settings_do_not_write(self):
        service = SettingsService(self.settings)
        for values in (
            {"beginner_rate": 101},
            {"beginner_price": -1},
            {"beginner_max": 0},
            {"beginner_max": 216},
            {"beginner_max": 215},
            {"test_mode": "invalid"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await service.update(values, 123, "admin", "test")
        self.settings.update_with_log.assert_not_awaited()
