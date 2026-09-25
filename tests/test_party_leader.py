import unittest
from unittest.mock import AsyncMock, patch

from services.party_service import Party, PartyError, PartyScreen, PartyService
from tests.test_party import guild_fixture
from tests.test_views import interaction
from views.party import PartyView
from views.party_exploration import PartyDifficultyView
from views.party_leader import LeaderSelect, LeaderTransferView, open_leader_transfer


class LeaderTransferRulesTests(unittest.TestCase):
    def test_transfer_preserves_roster_and_confirmation_but_invalidates_old_panel(self):
        for confirmation in ("", "old-confirmation"):
            with self.subTest(confirmation=confirmation):
                parties = {"p": Party("p", 10, 1, (1, 2), confirmation)}
                PartyService.apply_action(
                    parties,
                    {1: 10, 2: 10},
                    1,
                    "transfer_leader",
                    "p",
                    confirmation_id=confirmation,
                    target_user_id=2,
                )
                new = parties["p"]
                self.assertEqual((new.leader_id, new.members), (2, (1, 2)))
                self.assertEqual(bool(new.confirmation_id), bool(confirmation))
                if confirmation:
                    self.assertNotEqual(new.confirmation_id, confirmation)

    def test_invalid_target_nonleader_wrong_party_and_active_run_are_rejected(self):
        for user_id, target, party_id, run_id in (
            (2, 1, "p", ""),
            (1, 1, "p", ""),
            (1, 3, "p", ""),
            (1, 2, "old", ""),
            (1, 2, "p", "active"),
        ):
            party = Party("p", 10, 1, (1, 2), "", run_id)
            parties = {"p": party}
            with (
                self.subTest(user_id=user_id, target=target, run_id=run_id),
                self.assertRaises(PartyError),
            ):
                PartyService.apply_action(
                    parties,
                    {1: 10, 2: 10, 3: 10},
                    user_id,
                    "transfer_leader",
                    party_id,
                    confirmation_id="",
                    target_user_id=target,
                )
            self.assertEqual(parties["p"], party)


class LeaderTransferViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_panels_offer_leader_button_with_correct_permissions(self):
        party = Party("p", 10, 1, (1, 2))
        leader = PartyView(1, PartyScreen(10, (party,), party))
        follower = PartyView(2, PartyScreen(10, (party,), party))
        self.assertIn("リーダーを交代", [b.label for b in leader.children])
        self.assertNotIn("リーダーを交代", [b.label for b in follower.children])
        self.assertFalse(PartyDifficultyView(1, party).transfer_leader.disabled)
        self.assertTrue(PartyDifficultyView(2, party).transfer_leader.disabled)
        solo = Party("single", 10, 1, (1,))
        self.assertTrue(
            PartyView(1, PartyScreen(10, (), solo)).transfer_leader.disabled
        )
        active = Party("p", 10, 1, (1, 2), "confirmed", "run")
        self.assertNotIn(
            "リーダーを交代",
            [b.label for b in PartyView(1, PartyScreen(10, (), active)).children],
        )

    async def test_both_entry_buttons_load_current_party(self):
        party = Party("p", 10, 1, (1, 2))
        for view in (
            PartyView(1, PartyScreen(10, (), party)),
            PartyDifficultyView(1, party),
        ):
            event = interaction()
            with patch(
                "views.party_leader.open_leader_transfer", new=AsyncMock()
            ) as open_picker:
                await view.transfer_leader.callback(event)
            event.response.defer.assert_awaited_once()
            open_picker.assert_awaited_once_with(event, "p")

    async def test_picker_paginates_all_members_and_excludes_leader(self):
        party = Party("p", 10, 1, tuple(range(1, 64)))
        seen = []
        for page in range(3):
            view = LeaderTransferView(1, party, guild_fixture(), page)
            select = next(b for b in view.children if isinstance(b, LeaderSelect))
            self.assertLessEqual(len(select.options), 25)
            seen.extend(int(o.value) for o in select.options)
            self.assertEqual(view.previous.disabled, page == 0)
            self.assertEqual(view.next_page.disabled, page == 2)
        self.assertEqual(seen, list(range(2, 64)))
        event = interaction()
        event.user.id = 2
        self.assertFalse(await view.interaction_check(event))

    async def test_selection_binds_party_confirmation_and_target(self):
        party = Party("p", 10, 1, (1, 2), "confirmation")
        view = LeaderTransferView(1, party, guild_fixture())
        select = next(b for b in view.children if isinstance(b, LeaderSelect))
        select._values = ["2"]
        event = interaction()
        with patch("views.party_leader.show_party_screen", new=AsyncMock()) as show:
            await select.callback(event)
        show.assert_awaited_once_with(
            event,
            "transfer_leader",
            "p",
            confirmation_id="confirmation",
            target_user_id=2,
        )

    async def test_stale_entry_returns_to_current_panel_instead_of_opening_picker(self):
        event = interaction()
        current = Party("p", 10, 2, (1, 2))
        with (
            patch.object(
                PartyService,
                "run",
                new=AsyncMock(return_value=PartyScreen(10, (), current)),
            ),
            patch("views.party_leader.show_party_screen", new=AsyncMock()) as show,
        ):
            await open_leader_transfer(event, "p")
        show.assert_awaited_once_with(event)
        event.edit_original_response.assert_not_awaited()
        self.assertIn("現在のリーダー", event.followup.send.call_args.args[0])
