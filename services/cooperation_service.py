"""開始時のVC人数から、1回の宝探しに固定する協力効果を決める。"""

import secrets
from dataclasses import dataclass, replace
from fractions import Fraction

import discord

from consts.cooperation import COOP_DEFAULTS, MAX_EXPLORATIONS


@dataclass(frozen=True)
class CooperationBonus:
    people: int = 0
    tier: int = 0
    extra: int = 0
    multiplier: Fraction = Fraction(1)
    event: bool = False


class CooperationService:
    @staticmethod
    def count_members(member):
        voice = getattr(member, 'voice', None)
        channel = getattr(voice, 'channel', None)
        if channel is None or channel.type != discord.ChannelType.voice:
            return 0
        return len({person.id for person in channel.members if not person.bot})

    @staticmethod
    def validate(settings):
        s = COOP_DEFAULTS | settings
        for key in COOP_DEFAULTS:
            low, high = (0, 1) if key == 'coop_enabled' else (
                (2, 100) if key.endswith('_people') else
                (0, 20) if key.endswith('_extra') else
                (100, 500) if key.endswith('_multiplier') else (0, 10000)
            )
            if type(s[key]) is not int or not low <= s[key] <= high:
                raise ValueError(f'{key}は{low}〜{high}の整数で指定してください（確率・倍率は100倍値）。')
        if not s['coop_1_people'] < s['coop_2_people'] < s['coop_3_people']:
            raise ValueError('必要人数は段階1＜段階2＜段階3にしてください。')
        for suffix in ('extra', 'multiplier', 'chance'):
            if not s[f'coop_1_{suffix}'] <= s[f'coop_2_{suffix}'] <= s[f'coop_3_{suffix}']:
                raise ValueError('人数が増えたときに効果・イベント確率が下がらない設定にしてください。')

    @staticmethod
    def maximum(base, settings):
        s = COOP_DEFAULTS | settings
        extra = 0
        if s['coop_enabled']:
            extra = s['coop_3_extra']
            if s['coop_3_chance']:
                extra += s['coop_event_extra']
        return min(MAX_EXPLORATIONS, base + extra)

    @staticmethod
    def draw(people, settings, base):
        if type(people) is not int or people < 0:
            raise ValueError('VC人数が不正です。')
        s = COOP_DEFAULTS | settings
        tier = max((i for i in (1, 2, 3) if people >= s[f'coop_{i}_people']), default=0)
        if not s['coop_enabled'] or not tier:
            return CooperationBonus(people=people)
        chance = s[f'coop_{tier}_chance']
        event = chance > 0 and secrets.randbelow(10000) < chance
        extra = s[f'coop_{tier}_extra'] + (s['coop_event_extra'] if event else 0)
        multiplier = Fraction(s[f'coop_{tier}_multiplier'], 100)
        if event:
            multiplier *= Fraction(s['coop_event_multiplier'], 100)
        return CooperationBonus(people, tier, min(extra, MAX_EXPLORATIONS - base), multiplier, event)

    @staticmethod
    def apply_pool(pool, bonus):
        # 合計100へ正規化してから既存の色補正へ渡す。0%の宝物は復活させない。
        weights = [t.probability * (bonus.multiplier if t.rarity != 'normal' else 1) for t in pool]
        total = sum(weights)
        return tuple(replace(t, probability=w * 100 / total) for t, w in zip(pool, weights))
