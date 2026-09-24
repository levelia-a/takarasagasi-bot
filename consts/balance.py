"""百分率と倍率は小数第2位まで、DBでは100倍した整数で保持する。"""

BALANCE_DEFAULTS = {
    'map_copper_chance': 300, 'map_silver_chance': 100, 'map_gold_chance': 30,
    'map_copper_bonus': 5, 'map_silver_bonus': 10, 'map_gold_bonus': 20,
    'stage_forest_chance': 8000, 'stage_ruins_chance': 1700, 'stage_sanctuary_chance': 300,
    'stage_forest_multiplier': 100, 'stage_ruins_multiplier': 200, 'stage_sanctuary_multiplier': 400,
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
