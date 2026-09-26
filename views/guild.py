"""ギルドの作成・参加・所属表示。あいことばと確認は本人だけに表示する。"""

import discord

from services.guild_service import GuildError, GuildService
from views.common import BaseView, report_error


def safe_name(value):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))


def guild_embed(guild):
    embed = discord.Embed(
        title=f"🏰 {safe_name(guild.name)}", color=discord.Color.gold()
    )
    embed.description = (
        f"リーダー：<@{guild.leader_id}>\n人数：{len(guild.members)}/6人\n\n"
        + "\n".join(
            f"{'👑' if m.user_id == guild.leader_id else '👤'} <@{m.user_id}>"
            for m in guild.members
        )
        + "\n\n加入後は原則脱退できません。サーバーを脱退するとギルドからも脱退します。"
    )
    return embed


async def show_guild_screen(interaction):
    try:
        guild = await GuildService.screen(interaction.guild, interaction.user.id)
    except GuildError as error:
        await interaction.edit_original_response(
            content=str(error), embed=None, view=None
        )
        return
    if guild:
        embed = guild_embed(guild)
    else:
        embed = discord.Embed(
            title="🏰 ギルド作成/参加",
            description="最大6人のギルドを作成、またはあいことばで参加できます。\n"
            "1人が所属できるギルドは1つです。加入後は原則脱退できません。\n"
            "パーティーとは別の所属で、VCを退出しても維持されます。",
            color=discord.Color.gold(),
        )
    await interaction.edit_original_response(
        content=None,
        embed=embed,
        view=GuildView(interaction.user.id, guild is not None),
    )


class OwnerView(BaseView):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True


class GuildView(OwnerView):
    def __init__(self, owner_id, joined):
        super().__init__(owner_id)
        if joined:
            self.remove_item(self.create)
            self.remove_item(self.join)

    @discord.ui.button(label="ギルドを作成", style=discord.ButtonStyle.success)
    async def create(self, interaction, button):
        await interaction.response.send_modal(GuildModal(self.owner_id, "create"))

    @discord.ui.button(label="ギルドに参加", style=discord.ButtonStyle.primary)
    async def join(self, interaction, button):
        await interaction.response.send_modal(GuildModal(self.owner_id, "join"))

    @discord.ui.button(label="更新", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction, button):
        await interaction.response.defer()
        await show_guild_screen(interaction)

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        from views.home import HomeView, home_embed

        await interaction.response.edit_message(
            content=None, embed=home_embed(), view=HomeView(self.owner_id)
        )


class GuildModal(discord.ui.Modal):
    def __init__(self, owner_id, action):
        super().__init__(
            title="ギルドを作成" if action == "create" else "ギルドに参加", timeout=300
        )
        self.owner_id = owner_id
        self.action = action
        self.name_input = discord.ui.TextInput(
            label="ギルド名", min_length=1, max_length=32
        )
        self.passphrase = discord.ui.TextInput(
            label="あいことば", min_length=1, max_length=64
        )
        if action == "create":
            self.add_item(self.name_input)
        self.add_item(self.passphrase)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            confirmation = await GuildService.prepare(
                interaction.guild,
                self.owner_id,
                self.action,
                self.passphrase.value,
                self.name_input.value if self.action == "create" else None,
            )
        except GuildError as error:
            await interaction.edit_original_response(
                content=str(error), view=GuildView(self.owner_id, False)
            )
            return
        embed = guild_embed(confirmation.target)
        embed.title = (
            "🏰 ギルド作成の確認" if self.action == "create" else "🏰 ギルド参加の確認"
        )
        embed.description = (
            f"ギルド名：**{safe_name(confirmation.target.name)}**\n" + embed.description
        )
        if self.action == "create":
            embed.add_field(
                name="あいことば",
                value=safe_name(
                    GuildService.clean_text(self.passphrase.value, "あいことば", 64)
                ),
                inline=False,
            )
        embed.set_footer(text="「確定」で作成・加入します。確認の有効期限は5分です。")
        await interaction.edit_original_response(
            embed=embed, view=GuildConfirmView(confirmation)
        )

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class GuildConfirmView(OwnerView):
    def __init__(self, confirmation):
        super().__init__(confirmation.owner_id)
        self.confirmation = confirmation
        self.busy = False
        self.consumed = False

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        if self.busy or self.consumed:
            await interaction.response.send_message(
                "処理中、または確認済みです。トップ画面から所属をご確認ください。",
                ephemeral=True,
            )
            return
        self.busy = True
        try:
            await interaction.response.defer()
            try:
                guild = await GuildService.confirm(
                    interaction.guild, interaction.user.id, self.confirmation
                )
            except GuildError as error:
                self.consumed = True
                await interaction.edit_original_response(
                    content=str(error), embed=None, view=GuildView(self.owner_id, False)
                )
                self.stop()
                return
            self.consumed = True
            await interaction.edit_original_response(
                content="ギルドを作成しました。"
                if self.confirmation.action == "create"
                else "ギルドに参加しました。",
                embed=guild_embed(guild),
                view=GuildView(self.owner_id, True),
            )
            self.stop()
        finally:
            self.busy = False

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        if self.busy or self.consumed:
            await interaction.response.send_message(
                "処理中、または確認済みです。", ephemeral=True
            )
            return
        self.consumed = True
        await interaction.response.defer()
        await show_guild_screen(interaction)
        self.stop()
