"""公開トップ画面から本人専用のプレイ・パーティー画面へ進む。"""

import discord

from services.settings_service import SettingsService
from views.common import BaseView
from views.messages import treasure_panel


def home_embed():
    return discord.Embed(
        title="🗺️ 宝探し",
        description="宝の地図を手に入れて、冒険に出かけよう！\n\n"
        "👤 **1人でプレイ**\n難易度を選んで宝探しに出発します。\n\n"
        "🤝 **パーティーを組む**\n同じVCの仲間とパーティーを作成・参加できます。\n\n"
        "🏰 **ギルド作成/参加**\n最大6人のギルドに所属できます。加入後は原則脱退できません。",
        color=discord.Color.gold(),
    )


class HomeView(BaseView):
    def __init__(self, owner_id=None):
        super().__init__(timeout=300 if owner_id is not None else None)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True

    async def acknowledge(self, interaction):
        if self.owner_id is None:
            await interaction.response.defer(ephemeral=True, thinking=True)
        else:
            await interaction.response.defer()

    @discord.ui.button(
        label="1人でプレイ",
        emoji="👤",
        style=discord.ButtonStyle.primary,
        custom_id="takara_home_solo",
    )
    async def solo(self, interaction, button):
        from views.treasure import TreasureView

        await self.acknowledge(interaction)
        settings = await SettingsService.get_all()
        await interaction.edit_original_response(
            content=None,
            embed=treasure_panel(settings),
            view=TreasureView(interaction.user.id),
        )

    @discord.ui.button(
        label="パーティーを組む",
        emoji="🤝",
        style=discord.ButtonStyle.success,
        custom_id="takara_home_party",
    )
    async def party(self, interaction, button):
        from views.party import show_party_screen

        await self.acknowledge(interaction)
        await show_party_screen(interaction)

    @discord.ui.button(
        label="ギルド作成/参加",
        emoji="🏰",
        style=discord.ButtonStyle.secondary,
        custom_id="takara_home_guild",
    )
    async def game_guild(self, interaction, button):
        from views.guild import show_guild_screen

        await self.acknowledge(interaction)
        await show_guild_screen(interaction)
