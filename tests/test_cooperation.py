import unittest
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from consts.treasure import DEFAULT_SETTINGS, MAX_REWARD
from services.cooperation_service import CooperationBonus, CooperationService
from services.settings_service import SettingsService
from services.treasure_catalog_service import Treasure, TreasureCatalogError, TreasureCatalogService
from tests.test_views import interaction
from tests.treasure_fixtures import catalog_data
from views.cooperation_admin import CooperationModal, CooperationView, cooperation_settings_text
from services.treasure_service import Exploration
from views.messages import exploration_embed, map_start_embed, treasure_panel
from views.treasure import TreasureView


class CooperationTests(unittest.TestCase):
    def test_only_same_voice_channel_humans_are_counted(self):
        member = SimpleNamespace(id=1, bot=False, voice=None)
        self.assertEqual(CooperationService.count_members(member), 0)
        channel = SimpleNamespace(type=discord.ChannelType.voice, members=[
            member, SimpleNamespace(id=2, bot=False), SimpleNamespace(id=3, bot=True),
        ])
        member.voice = SimpleNamespace(channel=channel)
        self.assertEqual(CooperationService.count_members(member), 2)
        channel.members.pop(1)
        self.assertEqual(CooperationService.count_members(member), 1)
        channel.type = discord.ChannelType.stage_voice
        self.assertEqual(CooperationService.count_members(member), 0)
        self.assertEqual(CooperationService.count_members(SimpleNamespace()), 0)

    def test_tier_boundaries_without_event_and_disabled(self):
        for people, tier, extra, multiplier in (
            (0, 0, 0, 100), (1, 0, 0, 100), (2, 1, 1, 120),
            (3, 1, 1, 120), (4, 2, 2, 140), (5, 2, 2, 140),
            (6, 3, 3, 160), (1000, 3, 3, 160),
        ):
            with self.subTest(people=people), patch('services.cooperation_service.secrets.randbelow', return_value=9999) as roll:
                bonus = CooperationService.draw(people, DEFAULT_SETTINGS, 5)
                self.assertEqual((bonus.tier, bonus.extra, bonus.multiplier, bonus.event),
                                 (tier, extra, Fraction(multiplier, 100), False))
                self.assertEqual(roll.call_count, 1 if tier else 0)
        with patch('services.cooperation_service.secrets.randbelow') as roll:
            self.assertEqual(CooperationService.draw(8, DEFAULT_SETTINGS | {'coop_enabled': 0}, 5).extra, 0)
            roll.assert_not_called()

    def test_event_boundaries_and_exploration_cap(self):
        for people, chance, extra in ((2, 1000, 2), (4, 2000, 3), (6, 3000, 4)):
            for ticket, event in ((0, True), (chance - 1, True), (chance, False), (9999, False)):
                with patch('services.cooperation_service.secrets.randbelow', return_value=ticket):
                    bonus = CooperationService.draw(people, DEFAULT_SETTINGS, 5)
                    self.assertEqual(bonus.event, event)
                    self.assertEqual(bonus.extra, extra if event else extra - 1)
        with patch('services.cooperation_service.secrets.randbelow', return_value=0):
            bonus = CooperationService.draw(6, DEFAULT_SETTINGS, 214)
            self.assertEqual((bonus.extra, bonus.multiplier), (1, 2))
            self.assertEqual(CooperationService.draw(6, DEFAULT_SETTINGS, 215).extra, 0)
        with patch('services.cooperation_service.secrets.randbelow') as roll:
            self.assertFalse(CooperationService.draw(6, DEFAULT_SETTINGS | {'coop_3_chance': 0}, 5).event)
            roll.assert_not_called()
        with patch('services.cooperation_service.secrets.randbelow', return_value=9999):
            self.assertTrue(CooperationService.draw(6, DEFAULT_SETTINGS | {'coop_3_chance': 10000}, 5).event)

    def test_cooperation_and_color_multiply_all_rare_weights_exactly(self):
        pool = tuple(Treasure(str(i), r, 1, Fraction(25), 'beginner', r)
                     for i, r in enumerate(('normal', 'rare', 'epic', 'legendary')))
        pool += (Treasure('zero', 'zero', 1, Fraction(0), 'beginner', 'legendary'),)
        boosted = CooperationService.apply_pool(pool, CooperationBonus(multiplier=Fraction(3, 2)))
        self.assertEqual(sum(t.probability for t in boosted), 100)
        self.assertEqual(boosted[1].probability / boosted[0].probability, Fraction(3, 2))
        self.assertEqual(pool[0].probability, 25)
        # 協力1.5倍×赤4倍：通常200、各レア1200。0%の宝物は0のまま。
        for ticket, expected in ((199, 'normal'), (200, 'rare'), (1400, 'epic'), (2600, 'legendary'), (3799, 'legendary')):
            with patch('services.treasure_catalog_service.random.randrange', return_value=ticket) as roll:
                self.assertEqual(TreasureCatalogService.draw(boosted, 'red', DEFAULT_SETTINGS).rarity, expected)
                roll.assert_called_once_with(3800)
        self.assertEqual(boosted[-1].probability, 0)

    def test_validation_and_reward_limit_include_bonus(self):
        for invalid in ({'coop_enabled': 2}, {'coop_1_people': 1}, {'coop_2_people': 2},
                        {'coop_1_extra': -1}, {'coop_event_extra': 21}, {'coop_3_multiplier': 501},
                        {'coop_1_chance': 10001}, {'coop_1_multiplier': 99}, {'coop_event_extra': True},
                        {'coop_1_chance': 2500}, {'coop_1_extra': 4}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CooperationService.validate(DEFAULT_SETTINGS | invalid)
        catalog = TreasureCatalogService.validate_catalog(catalog_data())
        catalog['beginner'] = tuple(replace(t, price=MAX_REWARD // 5) for t in catalog['beginner'])
        SettingsService.validate_settings(DEFAULT_SETTINGS | {'coop_enabled': 0}, catalog)
        with self.assertRaises(TreasureCatalogError):
            SettingsService.validate_settings(DEFAULT_SETTINGS, catalog)
        self.assertEqual(CooperationService.maximum(214, DEFAULT_SETTINGS), 215)


class CooperationAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_button_passes_current_same_channel_count(self):
        event = interaction()
        event.user.bot = False
        channel = SimpleNamespace(type=discord.ChannelType.voice, members=[
            event.user, SimpleNamespace(id=2, bot=False), SimpleNamespace(id=3, bot=True),
        ])
        event.user.voice = SimpleNamespace(channel=channel)
        session = Exploration(1, 'user', 'beginner', 1000, 60, 6, 'normal')
        with patch('views.treasure.TreasureService.create', new_callable=AsyncMock, return_value=session) as create, patch(
            'views.treasure.TreasureService.explore', new_callable=AsyncMock
        ), patch('views.treasure.ExplorationView.show_result', new_callable=AsyncMock), patch(
            'views.treasure.asyncio.sleep', new_callable=AsyncMock
        ):
            await TreasureView().start(event, 'beginner')
            self.assertEqual(create.call_args.kwargs, {'vc_members': 2})

    async def test_event_display_and_disabled_panel(self):
        session = Exploration(1, 'user', 'beginner', 1000, 60, 9, 'normal',
                              cooperation=CooperationBonus(6, 3, 4, Fraction(2), True))
        for embed in (map_start_embed(session), exploration_embed(session)):
            self.assertIn('開始時6人', embed.description)
            self.assertIn('協力探索イベント発生', embed.description)
            self.assertIn('探索＋4回', embed.description)
            self.assertIn('重み×2', embed.description)
            self.assertLess(len(embed.description), 4096)
        self.assertNotIn('協力イベント', treasure_panel(DEFAULT_SETTINGS | {'coop_enabled': 0}).description)

    async def test_admin_only_and_modal_decimal_values(self):
        for group in ('1', '2', '3', 'event'):
            modal = CooperationModal(group, DEFAULT_SETTINGS)
            self.assertFalse(await modal.interaction_check(interaction()))
            self.assertTrue(await modal.interaction_check(interaction(admin=True)))
            self.assertLessEqual(len(modal.children), 5)
        self.assertFalse(await CooperationView().interaction_check(interaction()))
        self.assertLess(len(cooperation_settings_text(DEFAULT_SETTINGS)), 2000)
        modal = CooperationModal('1', DEFAULT_SETTINGS)
        for _, _, field in modal.inputs:
            field._value = field.default
        modal.inputs[2][2]._value = '1.35'
        event = interaction(admin=True)
        with patch('views.cooperation_admin.SettingsService.update', new_callable=AsyncMock) as update, patch(
            'views.cooperation_admin.SettingsService.get_all', new_callable=AsyncMock, return_value=DEFAULT_SETTINGS
        ):
            await modal.on_submit(event)
            self.assertEqual(update.call_args.args[0]['coop_1_multiplier'], 135)
            modal.inputs[0][2]._value = '2.5'
            update.reset_mock()
            await modal.on_submit(event)
            update.assert_not_awaited()
            self.assertIn('整数', event.edit_original_response.call_args.kwargs['content'])
