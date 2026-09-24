"""開始時に抽選し、宝探し全体に適用するステージ。"""

STAGES = {
    'forest': {'name': '🌲 迷いの森', 'color': 0x2ECC71, 'weight': 80, 'rare_multiplier': 1},
    'ruins': {'name': '🏛️ 古代遺跡', 'color': 0xD4AC0D, 'weight': 17, 'rare_multiplier': 2},
    'sanctuary': {'name': '⛩️ 秘境の神殿', 'color': 0x9B59B6, 'weight': 3, 'rare_multiplier': 4},
}

# 既存DBの値を読み込む際だけ利用する。新しいキーが存在すればそちらを優先。
LEGACY_STAGE_KEYS = {
    f'color_{old}_{suffix}': f'stage_{new}_{suffix}'
    for old, new in (('blue', 'forest'), ('green', 'ruins'), ('red', 'sanctuary'))
    for suffix in ('chance', 'multiplier')
}
