import secrets

from consts.rarity import EXPLORATION_COLORS


class ExplorationColorService:
    @staticmethod
    def draw():
        ticket = secrets.randbelow(sum(info['weight'] for info in EXPLORATION_COLORS.values()))
        for color, info in EXPLORATION_COLORS.items():
            if ticket < info['weight']:
                return color
            ticket -= info['weight']
        raise RuntimeError('探索色の抽選設定が不正です。')
