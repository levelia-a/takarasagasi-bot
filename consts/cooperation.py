"""VC協力設定。確率と倍率は100倍した整数で保存する。"""

COOP_DEFAULTS = {
    'coop_enabled': 1,
    'coop_event_extra': 1,
    'coop_event_multiplier': 125,
}
for tier, people, extra, multiplier, chance in (
    (1, 2, 1, 120, 1000),
    (2, 4, 2, 140, 2000),
    (3, 6, 3, 160, 3000),
):
    COOP_DEFAULTS.update({
        f'coop_{tier}_people': people,
        f'coop_{tier}_extra': extra,
        f'coop_{tier}_multiplier': multiplier,
        f'coop_{tier}_chance': chance,
    })

MAX_EXPLORATIONS = 215
