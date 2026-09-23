"""宝物のレア度と探索ごとの色演出。数値は仮設定。"""

RARITIES = {
    'normal': 'ノーマル',
    'rare': 'レア',
    'epic': 'エピック',
    'legendary': 'レジェンド',
}
EXPLORATION_COLORS = {
    'blue': {'name': '青', 'color': 0x3498DB, 'weight': 80, 'rare_multiplier': 1},
    'green': {'name': '緑', 'color': 0x2ECC71, 'weight': 17, 'rare_multiplier': 2},
    'red': {'name': '赤', 'color': 0xE74C3C, 'weight': 3, 'rare_multiplier': 4},
}
