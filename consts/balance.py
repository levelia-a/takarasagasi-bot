"""百分率と倍率は小数第2位まで、DBでは100倍した整数で保持する。"""

BALANCE_DEFAULTS = {
    'map_copper_chance': 300, 'map_silver_chance': 100, 'map_gold_chance': 30,
    'map_copper_bonus': 5, 'map_silver_bonus': 10, 'map_gold_bonus': 20,
    'color_blue_chance': 8000, 'color_green_chance': 1700, 'color_red_chance': 300,
    'color_blue_multiplier': 100, 'color_green_multiplier': 200, 'color_red_multiplier': 400,
    'rarity_profile_enabled': 0,
    'rarity_normal_chance': 7500, 'rarity_rare_chance': 2000,
    'rarity_epic_chance': 400, 'rarity_legendary_chance': 100,
}
CATALOG_SETTING_KEYS = {
    f'treasure_{difficulty}_{kind}'
    for difficulty in ('beginner', 'intermediate', 'advanced')
    for kind in ('probabilities', 'rarities')
}
BALANCE_DEFAULTS.update({key: '' for key in CATALOG_SETTING_KEYS})
