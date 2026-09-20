import discord
from discord import app_commands
from discord.ext import commands

from services.settings_service import SettingsService
from views.admin import AdminView
from views.common import require_admin
from views.messages import treasure_panel
from views.treasure import TreasureView


class TreasureCommands(commands.Cog):
    @app_commands.command(name="takara", description="宝探しパネルを表示します")
    @app_commands.guild_only()
    async def takara(self, interaction: discord.Interaction):
        """宝探しを開始する公開パネルを表示する。"""
        await interaction.response.defer()
        settings = await SettingsService.get_all()
        await interaction.edit_original_response(
            embed=treasure_panel(settings), view=TreasureView()
        )

    @app_commands.command(
        name="takara_admin", description="宝探し管理パネルを表示します"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def takara_admin(self, interaction: discord.Interaction):
        """管理者本人にだけ管理パネルを表示する。"""
        if not await require_admin(interaction):
            return
        embed = discord.Embed(
            title="⚙️ 宝アドミン",
            color=discord.Color.dark_gold(),
            description="価格・成功率・探索回数・運営状態・テストモード・統計・履歴などを管理できます。",
        )
        embed.add_field(
            name="⚠️ LIAについて",
            value="現在は既存のLIAシステムとは接続していません。\n価格・報酬は設定値としてのみ扱います。",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed, view=AdminView(), ephemeral=True
        )
