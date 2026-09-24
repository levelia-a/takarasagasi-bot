"""VC協力設定。確率と倍率は100倍した整数で保存する。"""

COOP_DEFAULTS = {
    'coop_enabled': 1,
}
COOP_EVENTS = {
    'passage': ('🗺️ 隠し通路を発見！', '仲間の声を頼りに、隠された道を見つけた！', 4000, 2, 100, 0),
    'presence': ('💎 宝物の気配', '仲間が壁の向こうから宝物の気配を感じ取った！', 3000, 0, 150, 0),
    'guide': ('🛡️ 仲間の道案内', '仲間が危険な道を見抜いてくれた！', 2000, 0, 100, 5),
    'vault': ('🌟 古代の宝物庫', '仲間と力を合わせ、宝物庫の扉を開いた！', 1000, 2, 150, 0),
}
EVENT_TEXT_KEYS = {f'coop_event_{key}_name' for key in COOP_EVENTS}
for key, (name, story, share, extra, multiplier, rate) in COOP_EVENTS.items():
    COOP_DEFAULTS.update({
        f'coop_event_{key}_name': name,
        f'coop_event_{key}_share': share,
        f'coop_event_{key}_extra': extra,
        f'coop_event_{key}_multiplier': multiplier,
        f'coop_event_{key}_rate': rate,
    })
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
