import discord
from discord.ext import commands
from discord import app_commands
import random
import sqlite3
import asyncio
from datetime import datetime

# =========================================================
# Bot設定
# =========================================================
TOKEN = ""
GUILD_ID = 1545489116127559680
DB_FILE = "takara.db"

# =========================================================
# 初期設定
# =========================================================
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
    "operation": 1,
    "test_mode": "normal",
}

# =========================================================
# Bot
# =========================================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# データベース
# =========================================================
def get_db():
    return sqlite3.connect(DB_FILE)

def setup_database():
    db = get_db()
    cur = db.cursor()

    
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
    settings_exists = cur.fetchone() is not None

    if settings_exists:
        cur.execute("PRAGMA table_info(settings)")
        columns = [row[1] for row in cur.fetchall()]
        if "key" not in columns or "value" not in columns:
            cur.execute("ALTER TABLE settings RENAME TO settings_old")
            print("古いsettingsテーブルを検出したため、自動修復しました。")

    # 設定
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    # 統計
    cur.execute("""
    CREATE TABLE IF NOT EXISTS statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        difficulty TEXT,
        start_price INTEGER,
        success_count INTEGER,
        final_reward INTEGER,
        result TEXT,
        failure_point INTEGER,
        is_test INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    # 管理者変更ログ
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        admin_name TEXT,
        action TEXT,
        detail TEXT,
        created_at TEXT
    )
    """)

    for key, value in DEFAULT_SETTINGS.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )

    db.commit()
    db.close()

def get_setting(key):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    db.close()
    if row is None:
        return DEFAULT_SETTINGS[key]
    value = row[0]
    try:
        return int(value)
    except ValueError:
        return value

def set_setting(key, value):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    INSERT INTO settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    db.commit()
    db.close()

def add_admin_log(interaction, action, detail):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    INSERT INTO admin_logs (admin_id, admin_name, action, detail, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        interaction.user.id, str(interaction.user), action, detail,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    db.commit()
    db.close()

def save_result(user, difficulty, start_price, success_count, final_reward,
                result, failure_point, is_test):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    INSERT INTO statistics (
        user_id, user_name, difficulty, start_price, success_count,
        final_reward, result, failure_point, is_test, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user.id, str(user), difficulty, start_price, success_count,
        final_reward, result, failure_point, is_test,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    db.commit()
    db.close()

DIFFICULTIES = {
    "beginner": {"name": "初級", "emoji": "🟢", "price_key": "beginner_price", "rate_key": "beginner_rate", "max_key": "beginner_max"},
    "intermediate": {"name": "中級", "emoji": "🔵", "price_key": "intermediate_price", "rate_key": "intermediate_rate", "max_key": "intermediate_max"},
    "advanced": {"name": "上級", "emoji": "🔴", "price_key": "advanced_price", "rate_key": "advanced_rate", "max_key": "advanced_max"},
}

def get_test_result():
    mode = get_setting("test_mode")
    if mode == "always_success":
        return True
    if mode == "always_fail":
        return False
    return None

class ExplorationView(discord.ui.View):
    def __init__(self, owner_id, difficulty, reward, exploration_count,
                 max_exploration, success_count, start_price):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.difficulty = difficulty
        self.reward = reward
        self.exploration_count = exploration_count
        self.max_exploration = max_exploration
        self.success_count = success_count
        self.start_price = start_price

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ この宝探しはあなたのものではありません。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="さらに奥へ", emoji="⚔️",
                       style=discord.ButtonStyle.danger, custom_id="takara_deeper")
    async def deeper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="🔎 **さらに奥を探索中……**", view=None)
        await asyncio.sleep(1.5)

        self.exploration_count += 1
        test_result = get_test_result()
        if test_result is None:
            rate = get_setting(DIFFICULTIES[self.difficulty]["rate_key"])
            success = random.randint(1, 100) <= rate
        else:
            success = test_result

        if not success:
            self.clear_items()
            await interaction.edit_original_response(
                content=(
                    f"💥 **探索失敗！**\n\n"
                    f"{DIFFICULTIES[self.difficulty]['name']}宝探しで失敗しました。\n"
                    f"今までの報酬 **{self.reward:,} LIA** はすべて失われます。\n\n"
                    f"💰 最終報酬：**0 LIA**"
                ),
                view=self
            )
            save_result(
                interaction.user, DIFFICULTIES[self.difficulty]["name"],
                self.start_price, self.success_count, 0, "failure",
                self.exploration_count, get_setting("test_mode") != "normal"
            )
            return

        self.success_count += 1
        self.reward *= 2

        if self.exploration_count >= self.max_exploration:
            self.clear_items()
            await interaction.edit_original_response(
                content=(
                    f"🎉 **最大探索回数到達！**\n\n"
                    f"{DIFFICULTIES[self.difficulty]['name']}宝探しを最後まで成功しました！\n\n"
                    f"✨ 成功回数：**{self.success_count}回**\n"
                    f"💰 獲得報酬：**{self.reward:,} LIA**"
                ),
                view=self
            )
            save_result(
                interaction.user, DIFFICULTIES[self.difficulty]["name"],
                self.start_price, self.success_count, self.reward,
                "max_success", None, get_setting("test_mode") != "normal"
            )
            return

        new_view = ExplorationView(
            self.owner_id, self.difficulty, self.reward, self.exploration_count,
            self.max_exploration, self.success_count, self.start_price
        )
        await interaction.edit_original_response(
            content=(
                f"✨ **探索成功！**\n\n報酬が2倍になりました！\n\n"
                f"🔎 探索回数：**{self.exploration_count}/{self.max_exploration}**\n"
                f"💰 現在の報酬：**{self.reward:,} LIA**\n\n"
                f"⚔️ **さらに奥へ進みますか？**"
            ),
            view=new_view
        )

    @discord.ui.button(label="引き返す", emoji="🏠",
                       style=discord.ButtonStyle.success, custom_id="takara_retreat")
    async def retreat(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.clear_items()
        await interaction.edit_original_response(
            content=(
                f"🏠 **無事に引き返しました！**\n\n"
                f"{DIFFICULTIES[self.difficulty]['name']}宝探しを終了します。\n\n"
                f"✨ 成功回数：**{self.success_count}回**\n"
                f"💰 確保した報酬：**{self.reward:,} LIA**"
            ),
            view=self
        )
        save_result(
            interaction.user, DIFFICULTIES[self.difficulty]["name"],
            self.start_price, self.success_count, self.reward,
            "retreat", None, get_setting("test_mode") != "normal"
        )

async def start_treasure(interaction, difficulty):
    config = DIFFICULTIES[difficulty]
    price = get_setting(config["price_key"])
    rate = get_setting(config["rate_key"])
    max_exploration = get_setting(config["max_key"])

    await interaction.response.send_message(
        f"{config['emoji']} **{config['name']}宝探し**\n\n"
        f"🗺️ {config['name']}宝の地図を手に入れた！\n\n"
        f"💰 必要LIA：**{price:,} LIA**",
        ephemeral=True
    )
    await asyncio.sleep(1)
    await interaction.edit_original_response(content="🔎 **探索中……**", view=None)
    await asyncio.sleep(1.5)

    test_result = get_test_result()
    success = random.randint(1, 100) <= rate if test_result is None else test_result

    if not success:
        await interaction.edit_original_response(
            content=f"💥 **探索失敗！**\n\n{config['name']}宝探しに失敗しました……。\n💰 報酬：**0 LIA**",
            view=None
        )
        save_result(interaction.user, config["name"], price, 0, 0, "failure", 1,
                    get_setting("test_mode") != "normal")
        return

    reward = price * 2
    view = ExplorationView(
        interaction.user.id, difficulty, reward, 1, max_exploration, 1, price
    )
    await interaction.edit_original_response(
        content=(
            f"🎉 **探索成功！**\n\n{config['name']}宝探しに成功しました！\n\n"
            f"✨ 成功回数：**1回**\n💰 現在の報酬：**{reward:,} LIA**\n\n"
            f"⚔️ **さらに奥へ進みますか？**\n失敗すると報酬はすべて失われます。"
        ),
        view=view
    )

class TreasureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="初級宝探し", emoji="🟢",
                       style=discord.ButtonStyle.success, custom_id="takara_beginner")
    async def beginner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if get_setting("operation") == 0:
            await interaction.response.send_message("🔴 現在、宝探しは停止中です。", ephemeral=True)
            return
        await start_treasure(interaction, "beginner")

    @discord.ui.button(label="中級宝探し", emoji="🔵",
                       style=discord.ButtonStyle.primary, custom_id="takara_intermediate")
    async def intermediate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if get_setting("operation") == 0:
            await interaction.response.send_message("🔴 現在、宝探しは停止中です。", ephemeral=True)
            return
        await start_treasure(interaction, "intermediate")

    @discord.ui.button(label="上級宝探し", emoji="🔴",
                       style=discord.ButtonStyle.danger, custom_id="takara_advanced")
    async def advanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        if get_setting("operation") == 0:
            await interaction.response.send_message("🔴 現在、宝探しは停止中です。", ephemeral=True)
            return
        await start_treasure(interaction, "advanced")

class AdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def admin_check(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 管理者のみ使用できます。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="現在の設定", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def settings_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(create_settings_text(), ephemeral=True)

    @discord.ui.button(label="価格設定", emoji="💰", style=discord.ButtonStyle.primary, row=0)
    async def price_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_modal(PriceModal())

    @discord.ui.button(label="成功率設定", emoji="🎯", style=discord.ButtonStyle.primary, row=0)
    async def rate_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_modal(RateModal())

    @discord.ui.button(label="探索回数設定", emoji="🔎", style=discord.ButtonStyle.primary, row=1)
    async def max_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_modal(MaxExplorationModal())

    @discord.ui.button(label="ON / OFF", emoji="🔄", style=discord.ButtonStyle.success, row=1)
    async def operation_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        current = get_setting("operation")
        new_value = 0 if current == 1 else 1
        set_setting("operation", new_value)
        add_admin_log(interaction, "運営ON/OFF変更", f"{current} → {new_value}")
        status = "🟢 ON" if new_value else "🔴 OFF"
        await interaction.response.send_message(
            f"宝探しの運営状態を **{status}** に変更しました。", ephemeral=True
        )

    @discord.ui.button(label="テストモード", emoji="🧪", style=discord.ButtonStyle.secondary, row=1)
    async def test_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(
            "🧪 テストモードを選択してください。", view=TestModeView(), ephemeral=True
        )

    @discord.ui.button(label="統計", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def stats_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(create_statistics_text(), ephemeral=True)

    @discord.ui.button(label="履歴", emoji="📜", style=discord.ButtonStyle.secondary, row=2)
    async def history_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(create_history_text(), ephemeral=True)

    @discord.ui.button(label="テストデータ削除", emoji="🧹", style=discord.ButtonStyle.danger, row=3)
    async def delete_test_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(
            "⚠️ テストデータを削除しますか？", view=DeleteTestView(), ephemeral=True
        )

    @discord.ui.button(label="管理ログ", emoji="🔐", style=discord.ButtonStyle.secondary, row=3)
    async def logs_button(self, interaction, button):
        if not await self.admin_check(interaction): return
        await interaction.response.send_message(create_admin_logs_text(), ephemeral=True)

class TestModeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="通常確率", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def normal(self, interaction, button):
        set_setting("test_mode", "normal")
        await interaction.response.edit_message(content="🎲 テストモードを **通常確率** にしました。", view=None)

    @discord.ui.button(label="必ず成功", emoji="✅", style=discord.ButtonStyle.success)
    async def success(self, interaction, button):
        set_setting("test_mode", "always_success")
        await interaction.response.edit_message(content="🧪 テストモードを **必ず成功** にしました。", view=None)

    @discord.ui.button(label="必ず失敗", emoji="❌", style=discord.ButtonStyle.danger)
    async def failure(self, interaction, button):
        set_setting("test_mode", "always_fail")
        await interaction.response.edit_message(content="🧪 テストモードを **必ず失敗** にしました。", view=None)

class DeleteTestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="削除する", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 管理者のみ使用できます。", ephemeral=True)
            return
        db = get_db()
        cur = db.cursor()
        cur.execute("DELETE FROM statistics WHERE is_test = 1")
        deleted = cur.rowcount
        db.commit()
        db.close()
        add_admin_log(interaction, "テストデータ削除", f"{deleted}件削除")
        await interaction.response.edit_message(
            content=f"🧹 テストデータを **{deleted}件** 削除しました。", view=None
        )

    @discord.ui.button(label="キャンセル", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

class PriceModal(discord.ui.Modal, title="💰 宝探し価格設定"):
    beginner = discord.ui.TextInput(label="初級価格", placeholder="1000", required=True, max_length=10)
    intermediate = discord.ui.TextInput(label="中級価格", placeholder="5000", required=True, max_length=10)
    advanced = discord.ui.TextInput(label="上級価格", placeholder="10000", required=True, max_length=10)

    async def on_submit(self, interaction):
        try:
            b, i, a = int(self.beginner.value), int(self.intermediate.value), int(self.advanced.value)
            if b < 0 or i < 0 or a < 0: raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 0以上の数字を入力してください。", ephemeral=True)
            return
        set_setting("beginner_price", b)
        set_setting("intermediate_price", i)
        set_setting("advanced_price", a)
        add_admin_log(interaction, "価格設定変更", f"初級={b}, 中級={i}, 上級={a}")
        await interaction.response.send_message(
            f"💰 価格設定を変更しました。\n\n🟢 初級：{b:,} LIA\n🔵 中級：{i:,} LIA\n🔴 上級：{a:,} LIA",
            ephemeral=True
        )

class RateModal(discord.ui.Modal, title="🎯 成功率設定"):
    beginner = discord.ui.TextInput(label="初級成功率（0～100）", placeholder="60", required=True)
    intermediate = discord.ui.TextInput(label="中級成功率（0～100）", placeholder="50", required=True)
    advanced = discord.ui.TextInput(label="上級成功率（0～100）", placeholder="40", required=True)

    async def on_submit(self, interaction):
        try:
            b, i, a = int(self.beginner.value), int(self.intermediate.value), int(self.advanced.value)
            if not all(0 <= x <= 100 for x in [b, i, a]): raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 0～100の数字を入力してください。", ephemeral=True)
            return
        set_setting("beginner_rate", b)
        set_setting("intermediate_rate", i)
        set_setting("advanced_rate", a)
        add_admin_log(interaction, "成功率変更", f"初級={b}%, 中級={i}%, 上級={a}%")
        await interaction.response.send_message(
            f"🎯 成功率を変更しました。\n\n🟢 初級：{b}%\n🔵 中級：{i}%\n🔴 上級：{a}%",
            ephemeral=True
        )

class MaxExplorationModal(discord.ui.Modal, title="🔎 最大探索回数設定"):
    beginner = discord.ui.TextInput(label="初級最大探索回数", placeholder="5", required=True)
    intermediate = discord.ui.TextInput(label="中級最大探索回数", placeholder="7", required=True)
    advanced = discord.ui.TextInput(label="上級最大探索回数", placeholder="10", required=True)

    async def on_submit(self, interaction):
        try:
            b, i, a = int(self.beginner.value), int(self.intermediate.value), int(self.advanced.value)
            if not all(x >= 1 for x in [b, i, a]): raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 1以上の数字を入力してください。", ephemeral=True)
            return
        set_setting("beginner_max", b)
        set_setting("intermediate_max", i)
        set_setting("advanced_max", a)
        add_admin_log(interaction, "最大探索回数変更", f"初級={b}, 中級={i}, 上級={a}")
        await interaction.response.send_message(
            f"🔎 最大探索回数を変更しました。\n\n🟢 初級：{b}回\n🔵 中級：{i}回\n🔴 上級：{a}回",
            ephemeral=True
        )

def create_settings_text():
    operation = "🟢 ON" if get_setting("operation") else "🔴 OFF"
    test_mode = get_setting("test_mode")
    test_names = {"normal": "通常確率", "always_success": "必ず成功", "always_fail": "必ず失敗"}
    return (
        "⚙️ **宝探し現在設定**\n\n"
        f"運営状態：{operation}\nテストモード：{test_names.get(test_mode, test_mode)}\n\n"
        f"🟢 **初級**\n💰 価格：{get_setting('beginner_price'):,} LIA\n🎯 成功率：{get_setting('beginner_rate')}%\n🔎 最大探索：{get_setting('beginner_max')}回\n\n"
        f"🔵 **中級**\n💰 価格：{get_setting('intermediate_price'):,} LIA\n🎯 成功率：{get_setting('intermediate_rate')}%\n🔎 最大探索：{get_setting('intermediate_max')}回\n\n"
        f"🔴 **上級**\n💰 価格：{get_setting('advanced_price'):,} LIA\n🎯 成功率：{get_setting('advanced_rate')}%\n🔎 最大探索：{get_setting('advanced_max')}回\n\n"
        "⚠️ 現在はLIAシステムとは未接続です。"
    )

def create_statistics_text():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT COUNT(*), COALESCE(SUM(start_price), 0),
           COALESCE(SUM(final_reward), 0), COALESCE(MAX(final_reward), 0)
    FROM statistics WHERE is_test = 0
    """)
    total, consumed, payout, max_payout = cur.fetchone()
    results = {}
    for key in DIFFICULTIES:
        name = DIFFICULTIES[key]["name"]
        cur.execute("SELECT COUNT(*) FROM statistics WHERE difficulty = ? AND is_test = 0", (name,))
        results[name] = cur.fetchone()[0]
    db.close()
    return (
        f"📊 **宝探し統計**\n\n総プレイ数：**{total:,}回**\n\n"
        f"🟢 初級：{results['初級']:,}回\n🔵 中級：{results['中級']:,}回\n🔴 上級：{results['上級']:,}回\n\n"
        f"仮想消費LIA：**{consumed:,} LIA**\n仮想報酬LIA：**{payout:,} LIA**\n"
        f"最大仮想報酬：**{max_payout:,} LIA**\n\n※現在は実際のLIA残高とは接続していません。"
    )

def create_history_text():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT user_name, difficulty, start_price, success_count, final_reward,
           result, failure_point, is_test, created_at
    FROM statistics ORDER BY id DESC LIMIT 10
    """)
    rows = cur.fetchall()
    db.close()
    if not rows:
        return "📜 **履歴**\n\nまだ履歴はありません。"
    text = "📜 **宝探し最新10件**\n\n"
    result_names = {"failure": "💥 失敗", "retreat": "🏠 引き返し", "max_success": "🏆 完走"}
    for row in rows:
        user_name, difficulty, start_price, success_count, final_reward, result, failure_point, is_test, created_at = row
        test_mark = " 🧪" if is_test else ""
        text += (
            f"**{user_name}**{test_mark}\n{difficulty} / 開始：{start_price:,} LIA\n"
            f"成功：{success_count}回 / 結果：{result_names.get(result, result)}\n"
            f"報酬：{final_reward:,} LIA\n{created_at}\n\n"
        )
    return text

def create_admin_logs_text():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    SELECT admin_name, action, detail, created_at
    FROM admin_logs ORDER BY id DESC LIMIT 10
    """)
    rows = cur.fetchall()
    db.close()
    if not rows:
        return "🔐 **管理ログ**\n\nまだログはありません。"
    text = "🔐 **管理者変更ログ 最新10件**\n\n"
    for admin_name, action, detail, created_at in rows:
        text += f"👤 {admin_name}\n🔧 {action}\n📝 {detail}\n🕐 {created_at}\n\n"
    return text

@bot.tree.command(name="takara", description="宝探しパネルを表示します")
async def takara(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🗺️ 宝探し",
        description=(
            "宝の地図を手に入れて、危険な場所を探索しよう！\n\n"
            "難易度が高いほど、必要なLIAも大きくなります。\n\n"
            "✨ 探索に成功すると報酬が2倍！\n"
            "💥 失敗すると獲得報酬はすべて失われます。\n"
            "🏠 引き返せば、その時点の報酬を確保できます。"
        ),
        color=discord.Color.gold()
    )
    embed.add_field(
        name="🟢 初級宝探し",
        value=f"必要LIA：{get_setting('beginner_price'):,}\n成功率：{get_setting('beginner_rate')}%\n最大探索：{get_setting('beginner_max')}回",
        inline=False
    )
    embed.add_field(
        name="🔵 中級宝探し",
        value=f"必要LIA：{get_setting('intermediate_price'):,}\n成功率：{get_setting('intermediate_rate')}%\n最大探索：{get_setting('intermediate_max')}回",
        inline=False
    )
    embed.add_field(
        name="🔴 上級宝探し",
        value=f"必要LIA：{get_setting('advanced_price'):,}\n成功率：{get_setting('advanced_rate')}%\n最大探索：{get_setting('advanced_max')}回",
        inline=False
    )
    embed.set_footer(text="※現在はLIAシステムとは未接続です")
    await interaction.response.send_message(embed=embed, view=TreasureView())

@bot.tree.command(name="takara_admin", description="宝探し管理パネルを表示します")
@app_commands.default_permissions(administrator=True)
async def takara_admin(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドは管理者専用です。", ephemeral=True)
        return
    embed = discord.Embed(
        title="⚙️ 宝アドミン",
        description=(
            "宝探しシステムの管理パネルです。\n\n"
            "価格・成功率・探索回数・運営状態・テストモード・統計・履歴などを管理できます。"
        ),
        color=discord.Color.dark_gold()
    )
    embed.add_field(
        name="⚠️ LIAについて",
        value="現在は既存のLIAシステムとは接続していません。\n価格・報酬は設定値としてのみ扱います。",
        inline=False
    )
    await interaction.response.send_message(embed=embed, view=AdminView(), ephemeral=True)

@bot.event
async def on_ready():
    setup_database()
    bot.add_view(TreasureView())
    guild = discord.Object(id=GUILD_ID)
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"コマンド同期成功！ {len(synced)}個のコマンドをサーバーへ同期しました。")
    except Exception as e:
        print(f"コマンド同期エラー：{e}")
    print(f"Bot起動成功！ {bot.user}")
    print("宝探しシステム起動完了！")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    print(f"スラッシュコマンドエラー：{error}")
    if interaction.response.is_done():
        try:
            await interaction.followup.send("❌ コマンド処理中にエラーが発生しました。", ephemeral=True)
        except Exception:
            pass
    else:
        try:
            await interaction.response.send_message("❌ コマンド処理中にエラーが発生しました。", ephemeral=True)
        except Exception:
            pass

bot.run(TOKEN)