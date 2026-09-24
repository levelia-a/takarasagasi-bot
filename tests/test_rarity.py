import unittest
from fractions import Fraction
from unittest.mock import patch

from consts.stages import STAGES
from consts.treasure import DEFAULT_SETTINGS
from services.settings_service import SettingsService
from services.stage_service import StageService
from services.treasure_catalog_service import Treasure, TreasureCatalogService, TreasureCatalogError
from services.treasure_service import Exploration
from tests.treasure_fixtures import catalog_data
from views.messages import exploration_embed, map_start_embed


class RarityTests(unittest.TestCase):
    def test_stage_draw_boundaries(self):
        for ticket, color in ((0, 'forest'), (79, 'forest'), (80, 'ruins'), (96, 'ruins'), (97, 'sanctuary'), (99, 'sanctuary')):
            with patch('services.stage_service.secrets.randbelow', return_value=ticket):
                self.assertEqual(StageService.draw(), color)

    def test_legacy_settings_migrate_and_new_keys_win_regardless_of_order(self):
        rows = [
            {'key': 'color_blue_chance', 'value': '7000'},
            {'key': 'color_green_chance', 'value': '2500'},
            {'key': 'color_red_chance', 'value': '500'},
            {'key': 'color_green_multiplier', 'value': '350'},
            {'key': 'stage_ruins_multiplier', 'value': '250'},
        ]
        for order in (rows, list(reversed(rows))):
            settings = SettingsService.build_settings(order)
            self.assertEqual([settings[f'stage_{key}_chance'] for key in STAGES], [7000, 2500, 500])
            self.assertEqual(settings['stage_ruins_multiplier'], 250)
            self.assertFalse(any(key.startswith('color_') for key in settings))
        self.assertEqual(SettingsService.build_settings([]), DEFAULT_SETTINGS)

    def test_rare_weight_boost_and_zero_probability(self):
        pool = (
            Treasure('a', 'normal', 1, Fraction(90), 'beginner', 'normal'),
            Treasure('b', 'rare', 1, Fraction(10), 'beginner', 'rare'),
            Treasure('c', 'disabled', 1, Fraction(0), 'beginner', 'legendary'),
        )
        for color, total in (('forest', 100), ('ruins', 110), ('sanctuary', 130)):
            for ticket, key in ((89, 'a'), (90, 'b'), (total - 1, 'b')):
                with patch('services.treasure_catalog_service.random.randrange', return_value=ticket) as draw:
                    self.assertEqual(TreasureCatalogService.draw(pool, color).key, key)
                    draw.assert_called_once_with(total)

    def test_all_rare_tiers_receive_multiplier(self):
        pool = tuple(Treasure(str(i), name, 1, Fraction(25), 'beginner', name)
                     for i, name in enumerate(('normal', 'rare', 'epic', 'legendary')))
        for ticket, rarity in ((24, 'normal'), (25, 'rare'), (124, 'rare'), (125, 'epic'), (225, 'legendary'), (324, 'legendary')):
            with patch('services.treasure_catalog_service.random.randrange', return_value=ticket):
                self.assertEqual(TreasureCatalogService.draw(pool, 'sanctuary').rarity, rarity)

    def test_rarity_validation_and_legacy_default(self):
        for invalid in ('unknown', None, [], 2):
            data = catalog_data()
            data['beginner'][0]['rarity'] = invalid
            with self.assertRaises(TreasureCatalogError):
                TreasureCatalogService.validate_catalog(data)
        data = catalog_data()
        del data['beginner'][0]['rarity']
        self.assertEqual(TreasureCatalogService.validate_catalog(data)['beginner'][0].rarity, 'normal')

    def test_embed_color_is_independent_of_gold_map(self):
        session = Exploration(1, 'user', 'beginner', 1000, 80, 5, 'normal', map_tier='gold')
        for color, info in STAGES.items():
            session.stage = color
            embed = exploration_embed(session)
            self.assertEqual(embed.color.value, info['color'])
            self.assertIn('成功率：80%', embed.description)
            self.assertIn(info['name'], embed.description)
            self.assertIn(info['name'], map_start_embed(session).description)
            self.assertIn('終了までこの場所', map_start_embed(session).description)
            self.assertNotIn('探索色', embed.description)
