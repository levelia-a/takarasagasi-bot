import secrets

from consts.stages import STAGES


class StageService:
    @staticmethod
    def draw(settings=None):
        weights = [(stage, settings[f'stage_{stage}_chance'] if settings else info['weight'])
                   for stage, info in STAGES.items()]
        ticket = secrets.randbelow(sum(weight for _, weight in weights))
        for stage, weight in weights:
            if ticket < weight:
                return stage
            ticket -= weight
        raise RuntimeError('ステージの抽選設定が不正です。')
