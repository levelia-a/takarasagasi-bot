import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from consts.treasure import DEFAULT_SETTINGS
from services.party_exploration_service import (
    Participant,
    PartyExplorationService,
    PartyRun,
)
from services.party_service import Party, PartyScreen, PartyService
from services.treasure_service import Exploration
from tests.test_party import guild_fixture
from tests.test_views import interaction
from tests.treasure_fixtures import install_test_catalog
from views.party import PartyView, show_party_screen
from views.party_exploration import (
    PartyDifficultyView,
    SharedExplorationView,
    shared_embed,
    update_shared_message,
)


def run_fixture():
    return PartyRun(
        "party",
        100,
        10,
        1,
        (
            Participant(1, "leader", "leader-session"),
            Participant(2, "member", "member-session"),
        ),
        Exploration(
            1, "leader", "beginner", 1000, 60, 5, "normal", settings=DEFAULT_SETTINGS
        ),
    )


class SharedViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(PartyExplorationService, "runs", {}))
        self.enterContext(patch.object(SharedExplorationView, "active", {}))
        install_test_catalog(self)

    async def test_confirm_button_is_leader_only_and_requires_two_members(self):
        for leader, members, enabled in [
            (1, (1,), False),
            (1, (1, 2), True),
            (2, (1, 2), False),
        ]:
            party = Party("p", 10, leader, members)
            view = PartyView(1, PartyScreen(10, (party,), party))
            confirm = next((b for b in view.children if b.label == "確定"), None)
            self.assertEqual(confirm is not None and not confirm.disabled, enabled)

    async def test_confirm_routes_to_group_difficulty_without_launching_solo(self):
        event = interaction()
        event.guild = guild_fixture()
        party = Party("p", 10, 1, (1, 2), "confirmed")
        with (
            patch.object(
                PartyService,
                "run",
                new=AsyncMock(return_value=PartyScreen(10, (), party)),
            ),
            patch(
                "views.party_exploration.SettingsService.get_all",
                new=AsyncMock(return_value=DEFAULT_SETTINGS),
            ),
            patch("views.party_exploration.refresh_invalid_runs", new=AsyncMock()),
        ):
            await show_party_screen(event, "confirm", "p")
        view = event.edit_original_response.call_args.kwargs["view"]
        self.assertIsInstance(view, PartyDifficultyView)
        self.assertIn("パーティーを組み直す", [b.label for b in view.children])
        self.assertEqual(view.party.confirmation_id, "confirmed")
        follower = PartyDifficultyView(2, party)
        self.assertTrue(follower.beginner.disabled)
        self.assertTrue(follower.reform.disabled)
        event.user.id = 3
        self.assertFalse(await view.interaction_check(event))

    async def test_reform_is_bound_to_confirmation_and_keeps_party_identity(self):
        event = interaction()
        party = Party("p", 10, 1, (1, 2), "old-confirmation")
        with patch("views.party.show_party_screen", new=AsyncMock()) as screen:
            await PartyDifficultyView(1, party).reform.callback(event)
        screen.assert_awaited_once_with(
            event, "reform", "p", confirmation_id="old-confirmation"
        )

    async def test_shared_controls_block_nonleader_but_inventory_is_available_to_members(
        self,
    ):
        run = run_fixture()
        view = SharedExplorationView(run)
        event = interaction()
        event.user.id = 2
        self.assertTrue(await view.interaction_check(event))
        with patch.object(PartyExplorationService, "step", new=AsyncMock()) as step:
            await view.deeper.callback(event)
        step.assert_not_awaited()
        with patch(
            "views.party_exploration.show_treasure_list", new=AsyncMock()
        ) as inventory:
            await view.inventory.callback(event)
        inventory.assert_awaited_once_with(event, 2, run.session.found_treasures, False)
        event.user.id = 3
        self.assertFalse(await view.interaction_check(event))

    async def test_publication_failure_cancels_group_without_advancing(self):
        event = interaction()
        event.guild = guild_fixture()
        event.guild.me = object()
        channel = SimpleNamespace(
            permissions_for=lambda _: SimpleNamespace(
                view_channel=True, send_messages=True, embed_links=True
            ),
            send=AsyncMock(side_effect=RuntimeError("send failed")),
        )
        event.guild.get_channel = lambda _: channel
        party = Party("p", 10, 1, (1, 2), "confirmed")
        run = run_fixture()
        with (
            patch.object(
                PartyExplorationService, "create", new=AsyncMock(return_value=run)
            ),
            patch.object(PartyExplorationService, "abort", new=AsyncMock()) as abort,
            patch.object(PartyExplorationService, "step", new=AsyncMock()) as step,
            self.assertRaises(RuntimeError),
        ):
            await PartyDifficultyView(1, party).start(event, "beginner")
        abort.assert_awaited_once()
        step.assert_not_awaited()

    async def test_successful_start_posts_one_shared_message_in_voice_chat(self):
        event = interaction()
        event.guild = guild_fixture()
        event.guild.me = object()
        message = SimpleNamespace(
            jump_url="https://discord.com/channels/100/10/99",
            edit=AsyncMock(),
            guild=event.guild,
        )
        channel = SimpleNamespace(
            permissions_for=lambda _: SimpleNamespace(
                view_channel=True, send_messages=True, embed_links=True
            ),
            send=AsyncMock(return_value=message),
        )
        event.guild.get_channel = lambda _: channel
        party = Party("p", 10, 1, (1, 2), "confirmed")
        run = run_fixture()
        with (
            patch.object(
                PartyExplorationService, "create", new=AsyncMock(return_value=run)
            ) as create,
            patch.object(PartyExplorationService, "step", new=AsyncMock()) as step,
        ):
            await PartyDifficultyView(1, party).start(event, "beginner")
        create.assert_awaited_once_with(event.guild, 1, "p", "confirmed", "beginner")
        channel.send.assert_awaited_once()
        step.assert_awaited_once_with(event.guild, run, 1, True, 0)
        self.assertIn(
            message.jump_url, event.edit_original_response.call_args.kwargs["content"]
        )
        self.assertEqual(run.message_url, message.jump_url)
        self.assertIs(SharedExplorationView.active[run.id].message, message)

    async def test_no_send_permission_does_not_claim_anyone(self):
        event = interaction()
        event.guild = guild_fixture()
        event.guild.me = object()
        event.guild.get_channel = lambda _: SimpleNamespace(
            permissions_for=lambda _: SimpleNamespace(
                view_channel=True, send_messages=False, embed_links=True
            )
        )
        with patch.object(PartyExplorationService, "create", new=AsyncMock()) as create:
            await PartyDifficultyView(1, Party("p", 10, 1, (1, 2), "confirmed")).start(
                event, "beginner"
            )
        create.assert_not_awaited()
        self.assertIn("権限", event.followup.send.call_args.args[0])

    async def test_result_display_failure_preserves_view_and_retry_updates_without_advancing(
        self,
    ):
        run = run_fixture()
        run.complete = True
        run.session.result = "retreat"
        run.session.exploration_count = 1
        old = SharedExplorationView(run)
        old.message = SimpleNamespace(
            edit=AsyncMock(side_effect=RuntimeError("display failed"))
        )
        SharedExplorationView.active[run.id] = old
        with self.assertRaises(RuntimeError):
            await update_shared_message(run)
        self.assertIs(SharedExplorationView.active[run.id], old)
        self.assertFalse(old.is_finished())
        old.message.edit.side_effect = None
        await update_shared_message(run)
        current = SharedExplorationView.active[run.id]
        self.assertEqual([b.label for b in current.children], ["宝物一覧"])
        self.assertTrue(old.is_finished())

    async def test_old_timeout_does_not_cancel_latest_step(self):
        run = run_fixture()
        view = SharedExplorationView(run)
        view.message = SimpleNamespace(guild=guild_fixture(), edit=AsyncMock())
        SharedExplorationView.active[run.id] = view
        run.version = 1
        await view.on_timeout()
        self.assertFalse(run.aborted)
        view.message.edit.assert_not_awaited()

    async def test_abort_view_is_explicit_and_hides_progress_buttons(self):
        run = run_fixture()
        run.aborted = "VCのメンバーが変わりました。"
        view = SharedExplorationView(run)
        self.assertEqual([b.label for b in view.children], ["宝物一覧"])
        self.assertIn(run.aborted, shared_embed(run).description)
