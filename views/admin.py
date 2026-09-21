import discord

from consts.treasure import DIFFICULTIES, TEST_MODES
from services.admin_service import AdminService
from services.settings_service import SettingsService
from views.common import AdminOnlyModal, AdminOnlyView, send_pages
from views.messages import history_entries, log_entries, settings_text, statistics_text


class SettingsModal(AdminOnlyModal):
    def __init__(self, kind):
        """指定した設定項目を難易度別に入力するモーダルを作る。"""
        titles = {
            "price": "💰 宝探し価格設定",
            "rate": "🎯 成功率設定",
            "max": "🔎 最大探索回数設定",
        }
        super().__init__(title=titles[kind])
        self.kind = kind
        self.inputs = {}
        for key, difficulty in DIFFICULTIES.items():
            field = discord.ui.TextInput(
                label=difficulty["name"], required=True, max_length=65
            )
            self.inputs[key] = field
            self.add_item(field)

    async def on_submit(self, interaction):
        """入力値を検証して設定を保存し、変更結果を表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            values = {
                f"{key}_{self.kind}": int(field.value)
                for key, field in self.inputs.items()
            }
            await SettingsService.update(
                values, interaction.user.id, str(interaction.user), self.title
            )
        except ValueError as error:
            await interaction.edit_original_response(
                content=f"❌ 入力値を確認してください。\n{error}"
            )
            return
        await interaction.edit_original_response(
            content="✅ 設定を変更しました。\n\n"
            + settings_text(await SettingsService.get_all())
        )


class UnlockSettingsModal(AdminOnlyModal):
    def __init__(self):
        super().__init__(title="🔓 難易度解放設定")
        self.intermediate = discord.ui.TextInput(
            label="中級解放までの初級探索回数", placeholder="10", required=True
        )
        self.advanced = discord.ui.TextInput(
            label="上級解放までの中級探索回数", placeholder="20", required=True
        )
        self.add_item(self.intermediate)
        self.add_item(self.advanced)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await SettingsService.update(
                {
                    "intermediate_unlock": int(self.intermediate.value),
                    "advanced_unlock": int(self.advanced.value),
                },
                interaction.user.id,
                str(interaction.user),
                "難易度解放設定変更",
            )
        except ValueError as error:
            await interaction.edit_original_response(
                content=f"❌ 入力値を確認してください。\n{error}"
            )
            return
        await interaction.edit_original_response(
            content="✅ 難易度解放条件を変更しました。\n\n"
            + settings_text(await SettingsService.get_all())
        )


class TestModeView(AdminOnlyView):
    def __init__(self):
        """テストモードを選ぶボタンを初期化する。"""
        super().__init__(timeout=120)

    async def change(self, interaction, mode):
        """テストモードを変更し、選択画面を閉じる。"""
        await interaction.response.defer()
        await SettingsService.update(
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
        """通常確率で抽選するモードに切り替える。"""
        await self.change(interaction, "normal")

    @discord.ui.button(label="必ず成功", emoji="✅", style=discord.ButtonStyle.success)
    async def success(self, interaction, button):
        """探索が必ず成功するテストモードに切り替える。"""
        await self.change(interaction, "always_success")

    @discord.ui.button(label="必ず失敗", emoji="❌", style=discord.ButtonStyle.danger)
    async def failure(self, interaction, button):
        """探索が必ず失敗するテストモードに切り替える。"""
        await self.change(interaction, "always_fail")


class DeleteTestView(AdminOnlyView):
    def __init__(self):
        """テスト履歴の削除確認ボタンを初期化する。"""
        super().__init__(timeout=120)

    @discord.ui.button(label="削除する", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction, button):
        """テスト履歴を削除し、削除件数を表示する。"""
        await interaction.response.defer()
        deleted = await AdminService.delete_test(
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
        """テスト履歴の削除を取り消し、確認画面を閉じる。"""
        await interaction.response.edit_message(
            content="キャンセルしました。", view=None
        )
        self.stop()


class AdminView(AdminOnlyView):
    def __init__(self):
        """設定変更や履歴確認に使う管理パネルを初期化する。"""
        super().__init__(timeout=300)

    @discord.ui.button(
        label="現在の設定", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0
    )
    async def settings_button(self, interaction, button):
        """現在の設定を管理者本人に表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(
            content=settings_text(await SettingsService.get_all())
        )

    @discord.ui.button(
        label="価格設定", emoji="💰", style=discord.ButtonStyle.primary, row=0
    )
    async def price_button(self, interaction, button):
        """価格設定の入力モーダルを開く。"""
        await interaction.response.send_modal(SettingsModal("price"))

    @discord.ui.button(
        label="成功率設定", emoji="🎯", style=discord.ButtonStyle.primary, row=0
    )
    async def rate_button(self, interaction, button):
        """成功率設定の入力モーダルを開く。"""
        await interaction.response.send_modal(SettingsModal("rate"))

    @discord.ui.button(
        label="探索回数設定", emoji="🔎", style=discord.ButtonStyle.primary, row=1
    )
    async def max_button(self, interaction, button):
        """最大探索回数の入力モーダルを開く。"""
        await interaction.response.send_modal(SettingsModal("max"))

    @discord.ui.button(
        label="ON / OFF", emoji="🔄", style=discord.ButtonStyle.success, row=1
    )
    async def operation_button(self, interaction, button):
        """運営状態のON・OFFを切り替え、結果を表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        value = await SettingsService.toggle_operation(
            interaction.user.id, str(interaction.user)
        )
        await interaction.edit_original_response(
            content=f"宝探しの運営状態を **{'🟢 ON' if value else '🔴 OFF'}** に変更しました。"
        )

    @discord.ui.button(
        label="テストモード", emoji="🧪", style=discord.ButtonStyle.secondary, row=1
    )
    async def test_button(self, interaction, button):
        """テストモードの選択画面を表示する。"""
        await interaction.response.send_message(
            "🧪 テストモードを選択してください。",
            view=TestModeView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="統計", emoji="📊", style=discord.ButtonStyle.secondary, row=2
    )
    async def stats_button(self, interaction, button):
        """テスト結果を除いた宝探しの統計を表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(
            content=statistics_text(await AdminService.statistics())
        )

    @discord.ui.button(
        label="履歴", emoji="📜", style=discord.ButtonStyle.secondary, row=2
    )
    async def history_button(self, interaction, button):
        """最新の宝探し履歴を文字数制限に合わせて表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_pages(interaction, history_entries(await AdminService.history()))

    @discord.ui.button(
        label="テストデータ削除", emoji="🧹", style=discord.ButtonStyle.danger, row=3
    )
    async def delete_test_button(self, interaction, button):
        """テスト履歴の削除確認画面を表示する。"""
        await interaction.response.send_message(
            "⚠️ テストデータを削除しますか？",
            view=DeleteTestView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="解放条件", emoji="🔓", style=discord.ButtonStyle.primary, row=4
    )
    async def unlock_button(self, interaction, button):
        """難易度の解放に必要な探索回数を変更する。"""
        await interaction.response.send_modal(UnlockSettingsModal())

    @discord.ui.button(
        label="管理ログ", emoji="🔐", style=discord.ButtonStyle.secondary, row=3
    )
    async def logs_button(self, interaction, button):
        """最新の管理者操作ログを文字数制限に合わせて表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_pages(interaction, log_entries(await AdminService.admin_logs()))
