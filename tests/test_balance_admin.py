import unittest
from fractions import Fraction
from unittest.mock import AsyncMock, patch

from consts.treasure import DEFAULT_SETTINGS
from services.balance_service import BalanceService
from services.exploration_color_service import ExplorationColorService
from services.map_service import MapService
from services.treasure_catalog_service import Treasure, TreasureCatalogService
from tests.treasure_fixtures import catalog_data
from tests.test_views import interaction
from views.balance_admin import BalanceModal, BalanceView, GROUPS, TreasureBalanceModal, balance_text


class BalanceTests(unittest.IsolatedAsyncioTestCase):
    def test_numeric_precision_and_invalid_totals(self):
        self.assertEqual(BalanceService.scaled_number('0.35'), 35)
        for invalid in ('NaN', 'Infinity', '-1', '0.001', '101'):
            with self.assertRaises(ValueError):
                BalanceService.scaled_number(invalid)
        for changes in ({'map_gold_chance': 10000}, {'color_red_chance': 301},
                        {'rarity_rare_chance': 1}, {'color_green_multiplier': 99}, {'map_gold_bonus': 101}):
            with self.assertRaises(ValueError):
                BalanceService.validate(DEFAULT_SETTINGS | changes)

    def test_custom_map_color_and_decimal_multiplier_reach_draw(self):
        settings = DEFAULT_SETTINGS | {'map_gold_chance': 10000, 'map_silver_chance': 0, 'map_copper_chance': 0,
            'color_blue_chance': 0, 'color_green_chance': 10000, 'color_red_chance': 0, 'color_green_multiplier': 250}
        with patch('secrets.randbelow', return_value=9999):
            self.assertEqual(MapService.draw(settings), 'gold')
            self.assertEqual(ExplorationColorService.draw(settings), 'green')
        pool = (Treasure('a', 'A', 1, Fraction(90), 'beginner'), Treasure('b', 'B', 1, Fraction(10), 'beginner', 'rare'))
        with patch('services.treasure_catalog_service.random.randrange', return_value=114) as roll:
            self.assertEqual(TreasureCatalogService.draw(pool, 'green', settings).key, 'b')
            roll.assert_called_once_with(115)

    def test_profile_and_individual_overrides_do_not_mutate_source(self):
        catalog = TreasureCatalogService.validate_catalog(catalog_data())
        settings = DEFAULT_SETTINGS | {'rarity_profile_enabled': 1,
            'treasure_beginner_probabilities': '15,15,15,15,15,8,7,5,4,1'}
        result = BalanceService.apply_catalog(catalog, settings)
        for rarity, expected in (('normal', 75), ('rare', 20), ('epic', 4), ('legendary', 1)):
            self.assertEqual(sum(t.probability for t in result['beginner'] if t.rarity == rarity), expected)
        self.assertEqual(catalog['beginner'][0].probability, 10)
        with self.assertRaises(ValueError):
            BalanceService.apply_catalog(catalog, settings | {'treasure_beginner_rarities': ','.join(['normal']*10)})

    async def test_admin_gates_and_prefilled_modals(self):
        for group in GROUPS:
            modal = BalanceModal(group, DEFAULT_SETTINGS)
            self.assertFalse(await modal.interaction_check(interaction()))
            self.assertTrue(await modal.interaction_check(interaction(admin=True)))
            self.assertLessEqual(len(modal.children), 5)
            self.assertTrue(all(child.default is not None for child in modal.children))
        self.assertFalse(await BalanceView().interaction_check(interaction()))
        self.assertLessEqual(len(balance_text(DEFAULT_SETTINGS)), 2000)

    async def test_modal_saves_scaled_values_and_handles_invalid_input(self):
        modal = BalanceModal('map_chance', DEFAULT_SETTINGS)
        event = interaction(admin=True)
        for _, _, field in modal.inputs:
            field._value = field.default
        modal.inputs[2][2]._value = '0.35'
        with patch('views.balance_admin.SettingsService.update', new_callable=AsyncMock) as update, patch(
            'views.balance_admin.SettingsService.get_all', new_callable=AsyncMock, return_value=DEFAULT_SETTINGS):
            await modal.on_submit(event)
            self.assertEqual(update.call_args.args[0]['map_gold_chance'], 35)
        modal.inputs[2][2]._value = 'NaN'
        with patch('views.balance_admin.SettingsService.update', new_callable=AsyncMock) as update:
            await modal.on_submit(event)
            update.assert_not_awaited()
            self.assertIn('❌', event.edit_original_response.call_args.kwargs['content'])

    async def test_treasure_modal_accepts_japanese_rarities(self):
        pool = TreasureCatalogService.validate_catalog(catalog_data())['beginner']
        modal = TreasureBalanceModal('beginner', pool, DEFAULT_SETTINGS)
        modal.chances._value = '\n'.join(['10']*10)
        modal.rarities._value = modal.rarities.default
        with patch('views.balance_admin.SettingsService.update', new_callable=AsyncMock) as update:
            await modal.on_submit(interaction(admin=True))
            values = update.call_args.args[0]
            self.assertEqual(values['treasure_beginner_probabilities'], ','.join(['10']*10))
            self.assertIn('legendary', values['treasure_beginner_rarities'])
