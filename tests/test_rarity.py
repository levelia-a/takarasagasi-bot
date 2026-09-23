import unittest
from fractions import Fraction
from unittest.mock import patch

from consts.rarity import EXPLORATION_COLORS
from services.exploration_color_service import ExplorationColorService
from services.treasure_catalog_service import Treasure, TreasureCatalogService, TreasureCatalogError
from services.treasure_service import Exploration
from tests.treasure_fixtures import catalog_data
from views.messages import exploration_embed


class RarityTests(unittest.TestCase):
    def test_color_draw_boundaries(self):
        for ticket, color in ((0, 'blue'), (79, 'blue'), (80, 'green'), (96, 'green'), (97, 'red'), (99, 'red')):
            with patch('services.exploration_color_service.secrets.randbelow', return_value=ticket):
                self.assertEqual(ExplorationColorService.draw(), color)

    def test_rare_weight_boost_and_zero_probability(self):
        pool = (
            Treasure('a', 'normal', 1, Fraction(90), 'beginner', 'normal'),
            Treasure('b', 'rare', 1, Fraction(10), 'beginner', 'rare'),
            Treasure('c', 'disabled', 1, Fraction(0), 'beginner', 'legendary'),
        )
        for color, total in (('blue', 100), ('green', 110), ('red', 130)):
            for ticket, key in ((89, 'a'), (90, 'b'), (total - 1, 'b')):
                with patch('services.treasure_catalog_service.random.randrange', return_value=ticket) as draw:
                    self.assertEqual(TreasureCatalogService.draw(pool, color).key, key)
                    draw.assert_called_once_with(total)

    def test_all_rare_tiers_receive_multiplier(self):
        pool = tuple(Treasure(str(i), name, 1, Fraction(25), 'beginner', name)
                     for i, name in enumerate(('normal', 'rare', 'epic', 'legendary')))
        for ticket, rarity in ((24, 'normal'), (25, 'rare'), (124, 'rare'), (125, 'epic'), (225, 'legendary'), (324, 'legendary')):
            with patch('services.treasure_catalog_service.random.randrange', return_value=ticket):
                self.assertEqual(TreasureCatalogService.draw(pool, 'red').rarity, rarity)

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
        for color, info in EXPLORATION_COLORS.items():
            session.exploration_color = color
            embed = exploration_embed(session)
            self.assertEqual(embed.color.value, info['color'])
            self.assertIn('成功率：80%', embed.description)
