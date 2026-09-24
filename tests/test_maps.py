import unittest
from unittest.mock import patch

from consts.maps import MAPS
from consts.stages import STAGES
from services.map_service import MapService
from services.treasure_service import Exploration, TreasureService
from views.messages import exploration_embed, map_start_embed


class MapTests(unittest.TestCase):
    def test_draw_boundaries(self):
        for ticket, tier in ((0, 'gold'), (29, 'gold'), (30, 'silver'), (129, 'silver'),
                             (130, 'copper'), (429, 'copper'), (430, 'normal'), (9999, 'normal')):
            with self.subTest(ticket=ticket), patch('services.map_service.secrets.randbelow', return_value=ticket):
                self.assertEqual(MapService.draw(), tier)

    def test_start_name_color_and_result_does_not_draw(self):
        for tier, prefix in (('normal', ''), ('copper', '銅の'), ('silver', '銀の'), ('gold', '金の')):
            for difficulty, label in (('beginner', '初級'), ('intermediate', '中級'), ('advanced', '上級')):
                session = Exploration(1, 'user', difficulty, 1000, 75, 5, 'normal', map_tier=tier)
                embed = map_start_embed(session)
                self.assertIn(f'{prefix}{label}の宝の地図を手に入れた！', embed.title)
                self.assertEqual(embed.color.value, MAPS[tier]['color'])
                session.exploration_count = 1
                session.result = 'failure'
                self.assertEqual(exploration_embed(session).color.value, STAGES['forest']['color'])
                session.exploration_count = 2
                for result in (None, 'failure', 'retreat', 'max_success'):
                    session.result = result
                    later = exploration_embed(session)
                    self.assertEqual(later.color.value, STAGES['forest']['color'])
                    self.assertIn('今回の成功率：75%', later.description)
                self.assertEqual(session.map_tier, tier)
                with patch.object(MapService, 'draw') as draw:
                    TreasureService.build_result(session)
                    draw.assert_not_called()
