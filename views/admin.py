import discord

from consts.treasure import DIFFICULTIES, TEST_MODES
from views.common import AdminOnlyModal, AdminOnlyView, send_pages
from views.messages import history_entries, log_entries, settings_text, statistics_text


class SettingsModal(AdminOnlyModal):
    def __init__(self, settings, kind):
        titles = {
            "price": "💰 宝探し価格設定",
            "rate": "🎯 成功率設定",
            "max": "🔎 最大探索回数設定",
        }
        super().__init__(title=titles[kind])
        self.settings = settings
        self.kind = kind
        self.inputs = {}
        for key, difficulty in DIFFICULTIES.items():
            field = discord.ui.TextInput(
                label=difficulty["name"], required=True, max_length=65
            )
            self.inputs[key] = field
            self.add_item(field)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            values = {
                f"{key}_{self.kind}": int(field.value)
                for key, field in self.inputs.items()
            }
            await self.settings.update(
                values, interaction.user.id, str(interaction.user), self.title
            )
        except ValueError as error:
            await interaction.edit_original_response(
                content=f"❌ 入力値を確認してください。\n{error}"
            )
            return
        await interaction.edit_original_response(
            content="✅ 設定を変更しました。\n\n"
            + settings_text(await self.settings.get_all())
        )


class TestModeView(AdminOnlyView):
    def __init__(self, settings):
        super().__init__(timeout=120)
        self.settings = settings

    async def change(self, interaction, mode):
        await interaction.response.defer()
        await self.settings.update(
            {"test_mode": mode},
            interaction.user.id,
            str(interaction.user),
            "テストモード変更",
        )
        await interaction.edit_original_response(
            content=f"🧪 テストモードを **{TEST_MODES[mode]}** にしました。", view=None
        )
        self.stop()

    @discord.ui.button(
        label="通常確率", emoji="🎲", style=discord.ButtonStyle.secondary
    )
    async def normal(self, interaction, button):
        await self.change(interaction, "normal")

    @discord.ui.button(label="必ず成功", emoji="✅", style=discord.ButtonStyle.success)
    async def success(self, interaction, button):
        await self.change(interaction, "always_success")

    @discord.ui.button(label="必ず失敗", emoji="❌", style=discord.ButtonStyle.danger)
    async def failure(self, interaction, button):
        await self.change(interaction, "always_fail")


class DeleteTestView(AdminOnlyView):
    def __init__(self, admin):
        super().__init__(timeout=120)
        self.admin = admin

    @discord.ui.button(label="削除する", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction, button):
        await interaction.response.defer()
        deleted = await self.admin.delete_test(
            interaction.user.id, str(interaction.user)
        )
        await interaction.edit_original_response(
            content=f"🧹 テストデータを **{deleted}件** 削除しました。", view=None
        )
        self.stop()

    @discord.ui.button(
        label="キャンセル", emoji="↩️", style=discord.ButtonStyle.secondary
    )
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(
            content="キャンセルしました。", view=None
        )
        self.stop()


class AdminView(AdminOnlyView):
    def __init__(self, settings, admin):
        super().__init__(timeout=300)
        self.settings = settings
        self.admin = admin

    @discord.ui.button(
        label="現在の設定", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0
    )
    async def settings_button(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(
            content=settings_text(await self.settings.get_all())
        )

    @discord.ui.button(
        label="価格設定", emoji="💰", style=discord.ButtonStyle.primary, row=0
    )
    async def price_button(self, interaction, button):
        await interaction.response.send_modal(SettingsModal(self.settings, "price"))

    @discord.ui.button(
        label="成功率設定", emoji="🎯", style=discord.ButtonStyle.primary, row=0
    )
    async def rate_button(self, interaction, button):
        await interaction.response.send_modal(SettingsModal(self.settings, "rate"))

    @discord.ui.button(
        label="探索回数設定", emoji="🔎", style=discord.ButtonStyle.primary, row=1
    )
    async def max_button(self, interaction, button):
        await interaction.response.send_modal(SettingsModal(self.settings, "max"))

    @discord.ui.button(
        label="ON / OFF", emoji="🔄", style=discord.ButtonStyle.success, row=1
    )
    async def operation_button(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        value = await self.settings.toggle_operation(
            interaction.user.id, str(interaction.user)
        )
        await interaction.edit_original_response(
            content=f"宝探しの運営状態を **{'🟢 ON' if value else '🔴 OFF'}** に変更しました。"
        )

    @discord.ui.button(
        label="テストモード", emoji="🧪", style=discord.ButtonStyle.secondary, row=1
    )
    async def test_button(self, interaction, button):
        await interaction.response.send_message(
            "🧪 テストモードを選択してください。",
            view=TestModeView(self.settings),
            ephemeral=True,
        )

    @discord.ui.button(
        label="統計", emoji="📊", style=discord.ButtonStyle.secondary, row=2
    )
    async def stats_button(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(
            content=statistics_text(await self.admin.statistics())
        )

    @discord.ui.button(
        label="履歴", emoji="📜", style=discord.ButtonStyle.secondary, row=2
    )
    async def history_button(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_pages(interaction, history_entries(await self.admin.history()))

    @discord.ui.button(
        label="テストデータ削除", emoji="🧹", style=discord.ButtonStyle.danger, row=3
    )
    async def delete_test_button(self, interaction, button):
        await interaction.response.send_message(
            "⚠️ テストデータを削除しますか？",
            view=DeleteTestView(self.admin),
            ephemeral=True,
        )

    @discord.ui.button(
        label="管理ログ", emoji="🔐", style=discord.ButtonStyle.secondary, row=3
    )
    async def logs_button(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_pages(interaction, log_entries(await self.admin.admin_logs()))
