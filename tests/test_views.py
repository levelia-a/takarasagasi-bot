import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from commands.treasure import TreasureCommands
from consts.treasure import DEFAULT_SETTINGS
from repositories.active_exploration_repository import TreasureSessionExpired
from repositories.result_repository import ResultRepository
from services.db_service import DbService
from services.progress_service import ProgressService
from services.settings_service import SettingsService
from services.treasure_service import Exploration, TreasureService
from views.admin import AdminView, SettingsModal, TestModeView
from views.common import send_pages
from views.messages import exploration_text
from views.treasure import ExplorationView, TreasureView


def interaction(admin=False):
    return SimpleNamespace(
        guild=object(),
        user=SimpleNamespace(
            id=1, guild_permissions=SimpleNamespace(administrator=admin)
        ),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            defer=AsyncMock(),
            is_done=Mock(return_value=False),
        ),
        edit_original_response=AsyncMock(),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_panel_and_commands(self):
        view = TreasureView()
        self.assertTrue(view.is_persistent())
        self.assertEqual(
            {item.custom_id for item in view.children},
            {"takara_beginner", "takara_intermediate", "takara_advanced"},
        )
        cog = TreasureCommands()
        self.assertEqual(
            {command.name for command in cog.get_app_commands()},
            {"takara", "takara_admin"},
        )

    async def test_admin_gates_include_modal_and_test_mode(self):
        for view in (
            AdminView(),
            TestModeView(),
            SettingsModal("rate"),
        ):
            with self.subTest(view=type(view).__name__):
                self.assertFalse(await view.interaction_check(interaction()))
                self.assertTrue(await view.interaction_check(interaction(admin=True)))

    async def test_other_user_cannot_play(self):
        view = ExplorationView(SimpleNamespace(user_id=2))
        self.assertFalse(await view.interaction_check(interaction()))

    async def test_rapid_button_click_is_rejected(self):
        view = ExplorationView(SimpleNamespace(user_id=1))
        view.busy = True
        event = interaction()
        with patch.object(
            TreasureService, "explore", new_callable=AsyncMock
        ) as explore:
            await view.act(event, True)
        event.response.send_message.assert_awaited_once()
        explore.assert_not_awaited()

    async def test_exploration_button_calls_service_and_clears_completed_view(self):
        self.enterContext(
            patch.object(
                SettingsService,
                "get_all",
                new=AsyncMock(return_value=DEFAULT_SETTINGS | {"beginner_max": 1}),
            )
        )
        db = MagicMock()
        connection = db.get_connection.return_value.__aenter__.return_value = (
            MagicMock()
        )
        connection.begin = AsyncMock()
        connection.commit = AsyncMock()
        connection.rollback = AsyncMock()
        self.enterContext(patch.object(DbService, "get_connection", db.get_connection))
        self.enterContext(
            patch.object(
                ResultRepository,
                "insert_statistics_record_if_session_id_not_exists",
                new_callable=AsyncMock,
            )
        )
        self.enterContext(
            patch("services.treasure_service.random.randint", return_value=1)
        )
        self.enterContext(
            patch.object(
                ProgressService, "record_exploration", new=AsyncMock(return_value=None)
            )
        )
        session = await TreasureService.create(1, "テスト", "beginner")
        view = ExplorationView(session)
        event = interaction()
        with patch("views.treasure.asyncio.sleep", new=AsyncMock()):
            await view.act(event, True)
        self.assertEqual(session.result, "max_success")
        self.assertIsNone(event.edit_original_response.call_args.kwargs["view"])

    async def test_failed_exploration_includes_unlock_notification(self):
        session = SimpleNamespace(
            result="failure",
            difficulty_name="初級",
            unlocked_difficulty="intermediate",
        )
        text = exploration_text(session)
        self.assertIn("探索失敗", text)
        self.assertIn("難易度解放", text)
        self.assertIn("中級宝探し", text)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

    async def test_long_history_is_split_without_second_defer(self):
        event = interaction()
        event.response.is_done.return_value = True
        text = "あ" * 5000
        await send_pages(event, [text])
        event.response.defer.assert_not_awaited()
        pages = [call.args[0] for call in event.followup.send.call_args_list]
        self.assertEqual("".join(pages), text)
        self.assertTrue(all(len(page) <= 1900 for page in pages))


class InitialExplorationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = Exploration(1, "test", "beginner", 1000, 60, 5, "normal")
        self.enterContext(
            patch.object(
                TreasureService, "create", new=AsyncMock(return_value=self.session)
            )
        )
        self.refresh = self.enterContext(
            patch.object(TreasureService, "_refresh_user", new_callable=AsyncMock)
        )
        self.release = self.enterContext(
            patch.object(TreasureService, "release_user", new_callable=AsyncMock)
        )
        self.progress = self.enterContext(
            patch.object(
                ProgressService, "record_exploration", new=AsyncMock(return_value=None)
            )
        )
        self.save = self.enterContext(
            patch.object(TreasureService, "save_result", new_callable=AsyncMock)
        )
        self.notice = self.enterContext(
            patch.object(
                ProgressService, "mark_unlock_notification", new_callable=AsyncMock
            )
        )
        self.roll = self.enterContext(
            patch("services.treasure_service.random.randint", return_value=1)
        )
        self.sleep = self.enterContext(
            patch("views.treasure.asyncio.sleep", new_callable=AsyncMock)
        )
        self.event = interaction()
        self.message = SimpleNamespace(edit=AsyncMock())
        self.view = None

        async def edit(**kwargs):
            if kwargs.get("view") is not None:
                self.view = kwargs["view"]
            return self.message

        self.event.edit_original_response.side_effect = edit

    async def test_initial_animation_rejects_both_buttons(self):
        entered, resume = asyncio.Event(), asyncio.Event()

        async def sleep(delay):
            if delay == 1.5:
                entered.set()
                await resume.wait()

        self.sleep.side_effect = sleep
        task = asyncio.create_task(TreasureView().start(self.event, "beginner"))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            for deeper in (False, True):
                event = interaction()
                await self.view.act(event, deeper)
                event.response.send_message.assert_awaited_once()
            self.assertEqual(self.session.exploration_count, 0)
            self.assertIsNone(self.session.result)
        finally:
            resume.set()
            await task
        self.assertEqual(self.session.exploration_count, 1)
        self.progress.assert_awaited_once()
        self.assertFalse(self.view.busy)

    async def test_initial_db_failure_keeps_pending_id_for_retreat(self):
        self.progress.side_effect = [RuntimeError("db failed"), None]
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        pending = self.session.pending_exploration_id
        self.assertIsNotNone(pending)
        self.assertFalse(self.view.busy)
        self.assertFalse(self.view.is_finished())
        self.release.assert_not_awaited()
        await self.view.act(interaction(), False)
        self.assertEqual(self.session.exploration_count, 1)
        self.assertEqual(self.session.result, "retreat")
        self.assertIsNone(self.session.pending_exploration_id)
        self.assertEqual(self.progress.await_args_list[1].args[2], pending)
        self.assertEqual(self.progress.await_args_list[1].args[3]["success_count"], 1)
        self.roll.assert_called_once()
        self.release.assert_awaited_once()

    async def test_error_before_first_roll_cannot_retreat_with_zero_explorations(self):
        self.refresh.side_effect = [RuntimeError("db failed"), None]
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        await self.view.act(interaction(), False)
        self.assertEqual(self.session.exploration_count, 1)
        self.assertIsNone(self.session.result)
        self.progress.assert_awaited_once()

    async def test_initial_final_display_failure_keeps_view_for_retry(self):
        self.session.max_exploration = 1
        original_edit = self.event.edit_original_response.side_effect

        async def edit(**kwargs):
            if kwargs.get("view", True) is None:
                raise RuntimeError("Discord unavailable")
            return await original_edit(**kwargs)

        self.event.edit_original_response.side_effect = edit
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        self.assertFalse(self.view.is_finished())
        self.assertFalse(self.view.busy)
        self.release.assert_not_awaited()
        retry = interaction()
        await self.view.act(retry, True)
        self.assertTrue(self.view.is_finished())
        self.assertIsNone(retry.edit_original_response.call_args.kwargs["view"])
        self.assertEqual(self.session.exploration_count, 1)
        self.progress.assert_awaited_once()
        self.release.assert_awaited_once()

    async def test_button_final_display_failure_does_not_stop_retry_view(self):
        await TreasureView().start(self.event, "beginner")
        retry = interaction()
        retry.edit_original_response.side_effect = RuntimeError("Discord unavailable")
        with self.assertRaises(RuntimeError):
            await self.view.act(retry, False)
        self.assertFalse(self.view.is_finished())
        self.release.assert_not_awaited()
        await self.view.act(interaction(), False)
        self.assertTrue(self.view.is_finished())
        self.assertEqual(self.session.exploration_count, 1)

    async def test_display_failure_does_not_ack_unlock(self):
        self.progress.return_value = "intermediate"
        original_edit = self.event.edit_original_response.side_effect

        async def edit(**kwargs):
            if self.session.exploration_count:
                raise RuntimeError("Discord unavailable")
            return await original_edit(**kwargs)

        self.event.edit_original_response.side_effect = edit
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        self.notice.assert_not_awaited()
        await self.view.act(interaction(), False)
        self.notice.assert_awaited_once_with(1, "intermediate")

    async def test_notice_save_failure_still_releases_finished_session(self):
        self.session.max_exploration = 1
        self.progress.return_value = "intermediate"
        self.notice.side_effect = RuntimeError("notice save failed")
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        self.release.assert_awaited_once_with(1, self.session.id)
        self.assertTrue(self.view.is_finished())

    async def test_display_failure_before_attaching_view_releases_claim(self):
        self.event.edit_original_response.side_effect = RuntimeError(
            "Discord unavailable"
        )
        with self.assertRaises(RuntimeError):
            await TreasureView().start(self.event, "beginner")
        self.release.assert_awaited_once_with(1, self.session.id)
        self.progress.assert_not_awaited()

    async def test_expired_session_removes_buttons_without_writing(self):
        await TreasureView().start(self.event, "beginner")
        self.refresh.side_effect = TreasureSessionExpired()
        event = interaction()
        await self.view.act(event, False)
        self.assertTrue(self.view.is_finished())
        self.assertIsNone(event.edit_original_response.call_args.kwargs["view"])
        self.assertIn(
            "操作期限", event.edit_original_response.call_args.kwargs["content"]
        )
        self.save.assert_not_awaited()
        self.progress.assert_awaited_once()
