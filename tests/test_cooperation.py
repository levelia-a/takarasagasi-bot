import unittest
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from consts.treasure import DEFAULT_SETTINGS, MAX_REWARD
from consts.cooperation import COOP_EVENTS
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
        for people, chance, extra in ((2, 1000, 3), (4, 2000, 4), (6, 3000, 5)):
            for ticket, event in ((0, True), (chance - 1, True), (chance, False), (9999, False)):
                with patch('services.cooperation_service.secrets.randbelow', side_effect=[ticket, 0]):
                    bonus = CooperationService.draw(people, DEFAULT_SETTINGS, 5)
                    self.assertEqual(bonus.event, event)
                    self.assertEqual(bonus.extra, extra if event else extra - 2)
        with patch('services.cooperation_service.secrets.randbelow', return_value=0):
            bonus = CooperationService.draw(6, DEFAULT_SETTINGS, 214)
            self.assertEqual((bonus.extra, bonus.multiplier), (1, Fraction(8, 5)))
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
                        {'coop_1_extra': -1}, {'coop_event_passage_extra': 21}, {'coop_3_multiplier': 501},
                        {'coop_1_chance': 10001}, {'coop_1_multiplier': 99}, {'coop_event_passage_extra': True},
                        {'coop_event_vault_share': 999}, {'coop_event_guide_rate': 101},
                        {'coop_event_guide_name': ''}, {'coop_event_guide_name': 'a\nb'},
                        {'coop_1_chance': 2500}, {'coop_1_extra': 4}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CooperationService.validate(DEFAULT_SETTINGS | invalid)
        catalog = TreasureCatalogService.validate_catalog(catalog_data())
        catalog['beginner'] = tuple(replace(t, price=MAX_REWARD // 5) for t in catalog['beginner'])
        SettingsService.validate_settings(DEFAULT_SETTINGS | {'coop_enabled': 0}, catalog)
        with self.assertRaises(TreasureCatalogError):
            SettingsService.validate_settings(DEFAULT_SETTINGS, catalog)
        self.assertEqual(CooperationService.maximum(214, DEFAULT_SETTINGS), 215)

    def test_all_event_distribution_boundaries_and_effects(self):
        for ticket, key, extra, multiplier, rate in (
            (0, 'passage', 3, Fraction(6, 5), 0), (3999, 'passage', 3, Fraction(6, 5), 0),
            (4000, 'presence', 1, Fraction(9, 5), 0), (6999, 'presence', 1, Fraction(9, 5), 0),
            (7000, 'guide', 1, Fraction(6, 5), 5), (8999, 'guide', 1, Fraction(6, 5), 5),
            (9000, 'vault', 3, Fraction(9, 5), 0), (9999, 'vault', 3, Fraction(9, 5), 0),
        ):
            with self.subTest(ticket=ticket), patch('services.cooperation_service.secrets.randbelow', side_effect=[0, ticket]) as roll:
                bonus = CooperationService.draw(2, DEFAULT_SETTINGS, 5)
                self.assertEqual((bonus.event_key, bonus.extra, bonus.multiplier, bonus.rate_bonus), (key, extra, multiplier, rate))
                self.assertEqual(bonus.event_name, COOP_EVENTS[key][0])
                self.assertEqual(roll.call_count, 2)

    def test_disabled_event_is_excluded_from_draw_and_reward_limit(self):
        settings = DEFAULT_SETTINGS | {f'coop_event_{key}_share': 0 for key in COOP_EVENTS}
        settings.update(coop_event_guide_share=10000, coop_event_passage_extra=20, coop_event_vault_extra=20)
        CooperationService.validate(settings)
        self.assertEqual(CooperationService.maximum(5, settings), 8)
        with patch('services.cooperation_service.secrets.randbelow', side_effect=[0, 9999]):
            self.assertEqual(CooperationService.draw(6, settings, 5).event_key, 'guide')

    def test_legacy_event_settings_do_not_apply_to_new_events(self):
        restored = SettingsService.build_settings([
            {'key': 'coop_event_extra', 'value': '20'},
            {'key': 'coop_event_multiplier', 'value': '500'},
            {'key': 'coop_event_guide_name', 'value': '安全な道案内'},
        ])
        self.assertNotIn('coop_event_extra', restored)
        self.assertEqual(restored['coop_event_guide_name'], '安全な道案内')
        with patch('services.cooperation_service.secrets.randbelow', side_effect=[0, 7000]):
            bonus = CooperationService.draw(2, restored, 5)
        self.assertEqual((bonus.extra, bonus.rate_bonus, bonus.event_name), (1, 5, '安全な道案内'))


class CooperationAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_modal_saves_name_and_effect_and_shares_modal_saves_all_four(self):
        for group in ('guide', 'shares'):
            modal = CooperationModal(group, DEFAULT_SETTINGS)
            for _, _, field in modal.inputs:
                field._value = field.default
            if group == 'guide':
                modal.inputs[0][2]._value = '仲間の導き'
                modal.inputs[2][2]._value = '1.25'
            with patch('views.cooperation_admin.SettingsService.update', new_callable=AsyncMock) as update, patch(
                'views.cooperation_admin.SettingsService.get_all', new_callable=AsyncMock, return_value=DEFAULT_SETTINGS
            ):
                await modal.on_submit(interaction(admin=True))
                values = update.call_args.args[0]
                if group == 'guide':
                    self.assertEqual(values['coop_event_guide_name'], '仲間の導き')
                    self.assertEqual(values['coop_event_guide_multiplier'], 125)
                    self.assertEqual(values['coop_event_guide_rate'], 5)
                else:
                    self.assertEqual(len(values), 4)
                    self.assertEqual(sum(values.values()), 10000)

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
                              cooperation=CooperationBonus(6, 3, 4, Fraction(2), True, 'guide', '**案内** @everyone', '仲間が道を発見！', 5))
        for embed in (map_start_embed(session), exploration_embed(session)):
            self.assertIn('開始時6人', embed.description)
            self.assertIn('協力探索イベント発生', embed.description)
            self.assertIn('探索＋4回', embed.description)
            self.assertIn('重み×2', embed.description)
            self.assertIn('成功率補正：＋5', embed.description)
            self.assertNotIn('@everyone', embed.description)
            self.assertLess(len(embed.description), 4096)
        self.assertNotIn('協力イベント', treasure_panel(DEFAULT_SETTINGS | {'coop_enabled': 0}).description)

    async def test_admin_only_and_modal_decimal_values(self):
        for group in ('1', '2', '3', 'shares', *COOP_EVENTS):
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
