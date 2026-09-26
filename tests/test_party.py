import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from commands.party import PartyEvents
from commands.treasure import TreasureCommands
from services.party_service import Party, PartyError, PartyScreen, PartyService
from tests.test_views import interaction
from views.home import HomeView
from views.party import PartySelect, PartyView, show_party_screen
from views.treasure import TreasureView


def guild_fixture():
    people = {
        uid: SimpleNamespace(id=uid, bot=False, display_name=f"user{uid}")
        for uid in range(1, 6)
    }
    channels = [
        SimpleNamespace(id=10, members=list(people.values())[:3]),
        SimpleNamespace(id=20, members=list(people.values())[3:]),
    ]
    return SimpleNamespace(
        id=100, unavailable=False, voice_channels=channels, get_member=people.get
    )


class PartyRulesTests(unittest.TestCase):
    def test_membership_restricted_to_voice_humans_and_single_party(self):
        parties = {}
        voices = {1: 10, 2: 10, 3: 20}
        with self.assertRaises(PartyError):
            PartyService.apply_action(parties, voices, 4, "create", None)
        PartyService.apply_action(parties, voices, 1, "create", None)
        party_id = next(iter(parties))
        PartyService.apply_action(parties, voices, 1, "create", None)
        self.assertEqual(len(parties), 1)
        with self.assertRaises(PartyError):
            PartyService.apply_action(parties, voices, 3, "join", party_id)
        PartyService.apply_action(parties, voices, 2, "join", party_id)
        PartyService.apply_action(parties, voices, 2, "join", party_id)
        self.assertEqual(parties[party_id].members, (1, 2))
        PartyService.apply_action(parties, voices, 3, "create", None)
        voices[3] = 10
        with self.assertRaises(PartyError):
            PartyService.apply_action(parties, voices, 3, "join", party_id)

    def test_move_transfers_leader_and_empty_party_disappears(self):
        party = Party("a", 10, 1, (1, 2, 3))
        parties = PartyService.reconcile({"a": party}, {1: 20, 2: 10, 3: 10})
        self.assertEqual(parties["a"].leader_id, 2)
        self.assertEqual(parties["a"].members, (2, 3))
        parties = PartyService.reconcile(parties, {3: 10})
        self.assertEqual(parties["a"].members, (3,))
        self.assertEqual(PartyService.reconcile(parties, {}), {})

    def test_stale_party_id_and_old_leader_cannot_delete_new_party(self):
        parties = {"new": Party("new", 10, 2, (1, 2))}
        for action, party_id in [
            ("leave", "old"),
            ("disband", "old"),
            ("disband", "new"),
        ]:
            with (
                self.subTest(action=action, party_id=party_id),
                self.assertRaises(PartyError),
            ):
                PartyService.apply_action(parties, {1: 10, 2: 10}, 1, action, party_id)
        self.assertEqual(parties["new"].members, (1, 2))
        PartyService.apply_action(parties, {1: 10, 2: 10}, 2, "leave", "new")
        self.assertEqual(parties["new"].leader_id, 1)
        PartyService.apply_action(parties, {1: 10}, 1, "disband", "new")
        self.assertFalse(parties)

    def test_unavailable_guild_is_not_treated_as_empty_voice(self):
        guild = guild_fixture()
        guild.voice_channels[0].members.append(SimpleNamespace(id=99, bot=True))
        self.assertNotIn(99, PartyService.voice_members(guild))
        guild.unavailable = True
        with self.assertRaises(PartyError):
            PartyService.voice_members(guild)


class PartyViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_publishes_persistent_home(self):
        event = interaction()
        await TreasureCommands.takara.callback(TreasureCommands(), event)
        view = event.edit_original_response.call_args.kwargs["view"]
        self.assertIsInstance(view, HomeView)
        self.assertTrue(view.is_persistent())
        self.assertEqual(
            [b.label for b in view.children], ["1人でプレイ", "パーティーを組む", "ギルド作成/参加"]
        )

    async def test_solo_opens_private_difficulty_and_back_keeps_home_private(self):
        event = interaction()
        with (
            patch("views.home.SettingsService.get_all", new=AsyncMock(return_value={})),
            patch("views.home.treasure_panel"),
        ):
            await HomeView().solo.callback(event)
        event.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        view = event.edit_original_response.call_args.kwargs["view"]
        self.assertIsInstance(view, TreasureView)
        self.assertEqual(view.owner_id, 1)
        await view.back.callback(event)
        home = event.response.edit_message.call_args.kwargs["view"]
        self.assertEqual(home.owner_id, 1)
        event.user.id = 2
        self.assertFalse(await view.interaction_check(event))
        self.assertFalse(await home.interaction_check(event))

    async def test_party_opens_private_screen_and_no_vc_guidance(self):
        event = interaction()
        event.guild = guild_fixture()
        with patch.object(
            PartyService, "run", new=AsyncMock(return_value=PartyScreen(None, (), None))
        ):
            await HomeView().party.callback(event)
        event.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        result = event.edit_original_response.call_args.kwargs
        self.assertIn("VCに参加", result["embed"].description)
        self.assertTrue(result["view"].create.disabled)
        self.assertNotIn("脱退する", [b.label for b in result["view"].children])

    async def test_join_select_and_pagination_cover_all_parties(self):
        parties = tuple(Party(str(i), 10, 1, (1,)) for i in range(26))
        screen = PartyScreen(10, parties, None)
        seen = []
        for page in range(3):
            view = PartyView(2, screen, page)
            embed = view.embed(guild_fixture())
            select = next(
                item for item in view.children if isinstance(item, PartySelect)
            )
            seen.extend(option.value for option in select.options)
            self.assertLess(len(embed), 6000)
            self.assertEqual(view.previous.disabled, page == 0)
            self.assertEqual(view.next_page.disabled, page == 2)
        self.assertEqual(seen, [p.id for p in parties])
        select._values = ["25"]
        with patch.object(view, "act", new=AsyncMock()) as action:
            await select.callback(interaction())
        action.assert_awaited_once_with(unittest.mock.ANY, "join", "25")

    async def test_own_party_permissions_pagination_and_bound_exit(self):
        party = Party("a", 10, 1, tuple(range(1, 121)))
        screen = PartyScreen(10, (party,), party)
        view = PartyView(1, screen, 11)
        self.assertEqual(view.page_count, 12)
        self.assertLess(len(view.embed(guild_fixture())), 6000)
        self.assertNotIn("パーティーを作成", [b.label for b in view.children])
        event = interaction()
        with patch.object(view, "act", new=AsyncMock()) as action:
            await view.leave.callback(event)
        action.assert_awaited_once_with(event, "leave", "a")
        other = PartyView(2, screen)
        self.assertNotIn("解散する", [b.label for b in other.children])
        self.assertFalse(await other.interaction_check(event))

    async def test_stale_action_renders_current_screen_and_error(self):
        event = interaction()
        event.guild = guild_fixture()
        with patch.object(
            PartyService,
            "run",
            new=AsyncMock(
                side_effect=[
                    PartyError("所属が変わっています。"),
                    PartyScreen(10, (), None),
                ]
            ),
        ):
            await show_party_screen(event, "leave", "old")
        self.assertIn(
            "所属が変わっています",
            event.edit_original_response.call_args.kwargs["content"],
        )
        self.assertIsNone(
            event.edit_original_response.call_args.kwargs["view"].screen.own
        )

    async def test_voice_events_ignore_mute_and_periodic_retry_checks_guild(self):
        guild = guild_fixture()
        bot = SimpleNamespace(is_ready=lambda: True, guilds=[guild])
        cog = PartyEvents(bot)
        member = SimpleNamespace(bot=False, guild=guild)
        before = SimpleNamespace(channel=10)
        with patch.object(PartyService, "run", new=AsyncMock()) as reconcile:
            await cog.on_voice_state_update(member, before, before)
            reconcile.assert_not_awaited()
            await cog.on_voice_state_update(member, before, SimpleNamespace(channel=20))
            reconcile.assert_awaited_once_with(guild)
            await cog.reconcile_parties()
            self.assertEqual(reconcile.await_count, 2)
