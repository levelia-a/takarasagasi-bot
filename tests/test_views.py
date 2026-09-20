import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from commands.treasure import TreasureCommands
from consts.treasure import DEFAULT_SETTINGS
from services.treasure_service import TreasureService
from views.admin import AdminView, SettingsModal, TestModeView
from views.common import send_pages
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
        view = TreasureView(AsyncMock())
        self.assertTrue(view.is_persistent())
        self.assertEqual(
            {item.custom_id for item in view.children},
            {"takara_beginner", "takara_intermediate", "takara_advanced"},
        )
        cog = TreasureCommands(None, None, None)
        self.assertEqual(
            {command.name for command in cog.get_app_commands()},
            {"takara", "takara_admin"},
        )

    async def test_admin_gates_include_modal_and_test_mode(self):
        for view in (
            AdminView(None, None),
            TestModeView(None),
            SettingsModal(None, "rate"),
        ):
            with self.subTest(view=type(view).__name__):
                self.assertFalse(await view.interaction_check(interaction()))
                self.assertTrue(await view.interaction_check(interaction(admin=True)))

    async def test_other_user_cannot_play(self):
        view = ExplorationView(None, SimpleNamespace(user_id=2))
        self.assertFalse(await view.interaction_check(interaction()))

    async def test_rapid_button_click_is_rejected(self):
        view = ExplorationView(AsyncMock(), SimpleNamespace(user_id=1))
        view.busy = True
        event = interaction()
        await view.act(event, True)
        event.response.send_message.assert_awaited_once()
        view.service.explore.assert_not_awaited()

    async def test_exploration_button_calls_service_and_clears_completed_view(self):
        settings = AsyncMock()
        settings.get_all.return_value = DEFAULT_SETTINGS | {"beginner_max": 1}
        db = MagicMock()
        db.get_connection.return_value.__aenter__.return_value = MagicMock()
        service = TreasureService(db, settings, AsyncMock(), lambda low, high: 1)
        session = await service.create(1, "テスト", "beginner")
        view = ExplorationView(service, session)
        event = interaction()
        with patch("views.treasure.asyncio.sleep", new=AsyncMock()):
            await view.act(event, True)
        self.assertEqual(session.result, "max_success")
        self.assertIsNone(event.edit_original_response.call_args.kwargs["view"])

    async def test_long_history_is_split_without_second_defer(self):
        event = interaction()
        event.response.is_done.return_value = True
        text = "あ" * 5000
        await send_pages(event, [text])
        event.response.defer.assert_not_awaited()
        pages = [call.args[0] for call in event.followup.send.call_args_list]
        self.assertEqual("".join(pages), text)
        self.assertTrue(all(len(page) <= 1900 for page in pages))
