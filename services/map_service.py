import secrets

from consts.maps import MAP_DROP_WEIGHTS


class MapService:
    @staticmethod
    def draw(settings=None):
        ticket = secrets.randbelow(10000)
        weights = MAP_DROP_WEIGHTS if settings is None else tuple(
            (tier, settings[f'map_{tier}_chance']) for tier in ('gold', 'silver', 'copper')
        )
        for tier, weight in weights:
            if ticket < weight:
                return tier
            ticket -= weight
        return 'normal'
