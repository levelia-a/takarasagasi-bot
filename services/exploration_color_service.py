import secrets

from consts.rarity import EXPLORATION_COLORS


class ExplorationColorService:
    @staticmethod
    def draw(settings=None):
        weights = [(color, settings[f'color_{color}_chance'] if settings else info['weight'])
                   for color, info in EXPLORATION_COLORS.items()]
        ticket = secrets.randbelow(sum(weight for _, weight in weights))
        for color, weight in weights:
            if ticket < weight:
                return color
            ticket -= weight
        raise RuntimeError('探索色の抽選設定が不正です。')
