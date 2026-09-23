import secrets

from consts.maps import MAP_DROP_WEIGHTS


class MapService:
    @staticmethod
    def draw():
        ticket = secrets.randbelow(10000)
        for tier, weight in MAP_DROP_WEIGHTS:
            if ticket < weight:
                return tier
            ticket -= weight
        return 'normal'
