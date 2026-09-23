from dataclasses import replace
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from consts.balance import BALANCE_DEFAULTS
from consts.rarity import RARITIES


class BalanceService:
    @staticmethod
    def scaled_number(text):
        try:
            number = Decimal(str(text).strip())
            scaled = number * 100
            if not number.is_finite() or scaled != scaled.to_integral_value() or not 0 <= scaled <= 10000:
                raise ValueError
            return int(scaled)
        except (ValueError, InvalidOperation):
            raise ValueError('数値は0〜100、小数第2位までで入力してください。') from None

    @staticmethod
    def validate(settings):
        s = BALANCE_DEFAULTS | settings
        for key in BALANCE_DEFAULTS:
            if key.endswith(('_chance', '_bonus', '_multiplier')):
                value = s[key]
                limit = 100 if key.endswith('_bonus') else 10000
                minimum = 100 if key.endswith('_multiplier') else 0
                if type(value) is not int or not minimum <= value <= limit:
                    raise ValueError(f'{key}: 設定値が範囲外です。倍率は1〜100倍、補正は0〜100ポイントです。')
        if sum(s[f'map_{tier}_chance'] for tier in ('copper', 'silver', 'gold')) > 10000:
            raise ValueError('銅・銀・金の出現率合計は100%以下にしてください。残りが通常地図になります。')
        for group, names in (('color', ('blue', 'green', 'red')), ('rarity', tuple(RARITIES))):
            if sum(s[f'{group}_{name}_chance'] for name in names) != 10000:
                raise ValueError('探索色とレア度配分の出現率は、それぞれ合計100%にしてください。')
        if s['rarity_profile_enabled'] not in (0, 1):
            raise ValueError('レア度配分の設定が不正です。')

    @staticmethod
    def apply_catalog(catalog, settings):
        result = {}
        for difficulty, pool in catalog.items():
            probabilities = settings.get(f'treasure_{difficulty}_probabilities', '')
            rarities = settings.get(f'treasure_{difficulty}_rarities', '')
            if (probabilities or rarities) and not pool:
                raise ValueError(f'{difficulty}: 宝物ファイルを設定してから変更してください。')
            if probabilities:
                values = [BalanceService.scaled_number(v) for v in probabilities.split(',')]
                if len(values) != len(pool) or sum(values) != 10000:
                    raise ValueError('宝物10種類の出現率は、合計100%にしてください。')
                pool = tuple(replace(t, probability=Fraction(v, 100)) for t, v in zip(pool, values))
            if rarities:
                values = rarities.split(',')
                if len(values) != len(pool) or any(v not in RARITIES for v in values):
                    raise ValueError('宝物10種類それぞれのレア度を指定してください。')
                pool = tuple(replace(t, rarity=v) for t, v in zip(pool, values))
            if pool and settings.get('rarity_profile_enabled', 0):
                totals = {r: sum(t.probability for t in pool if t.rarity == r) for r in RARITIES}
                for rarity, total in totals.items():
                    if settings[f'rarity_{rarity}_chance'] > 0 and total == 0:
                        raise ValueError(f'{difficulty}: {RARITIES[rarity]}の宝物に正の出現率が必要です。')
                pool = tuple(replace(t, probability=(
                    t.probability * Fraction(settings[f'rarity_{t.rarity}_chance'], 100) / totals[t.rarity]
                    if totals[t.rarity] else Fraction(0)
                )) for t in pool)
            result[difficulty] = pool
        return result
