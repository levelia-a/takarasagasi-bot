"""地図の仮設定。確率は10000分率、効果は成功率への加算ポイント。"""

MAPS = {
    'normal': {'name': '通常の宝の地図', 'bonus': 0, 'color': 0x5865F2},
    'copper': {'name': '銅の宝の地図', 'bonus': 5, 'color': 0xB87333},
    'silver': {'name': '銀の宝の地図', 'bonus': 10, 'color': 0xC0C0C0},
    'gold': {'name': '金の宝の地図', 'bonus': 20, 'color': 0xFFD700},
}
MAP_DROP_WEIGHTS = (('gold', 30), ('silver', 100), ('copper', 300))
