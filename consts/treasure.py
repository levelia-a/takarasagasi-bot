DEFAULT_SETTINGS = {
    "beginner_price": 1000,
    "beginner_rate": 60,
    "beginner_max": 5,
    "intermediate_price": 5000,
    "intermediate_rate": 50,
    "intermediate_max": 7,
    "advanced_price": 10000,
    "advanced_rate": 40,
    "advanced_max": 10,
    "intermediate_unlock": 10,
    "advanced_unlock": 20,
    "operation": 1,
    "test_mode": "normal",
}

DIFFICULTIES = {
    "beginner": {"name": "初級", "emoji": "🟢"},
    "intermediate": {"name": "中級", "emoji": "🔵"},
    "advanced": {"name": "上級", "emoji": "🔴"},
}

TEST_MODES = {
    "normal": "通常確率",
    "always_success": "必ず成功",
    "always_fail": "必ず失敗",
}
RESULT_NAMES = {
    "failure": "💥 失敗",
    "retreat": "🏠 引き返し",
    "max_success": "🏆 完走",
}
# MySQL DECIMAL(65, 0) に収まる組み合わせのみ受け付ける。
MAX_REWARD = 10**65 - 1
