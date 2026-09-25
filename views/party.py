"""本人専用のパーティー募集一覧・所属画面。操作ごとにDBとVCを再確認する。"""

import discord

from services.party_service import PartyError, PartyService
from views.common import BaseView
from views.home import HomeView, home_embed

PAGE_SIZE = 10


def member_name(guild, user_id):
    member = guild.get_member(user_id)
    raw = member.display_name if member else str(user_id)
    return discord.utils.escape_mentions(discord.utils.escape_markdown(raw[:32]))


async def show_party_screen(interaction, action="refresh", party_id=None, page=0):
    notice = None
    try:
        screen = await PartyService.run(
            interaction.guild, interaction.user.id, action, party_id
        )
    except PartyError as error:
        notice = str(error)
        try:
            screen = await PartyService.run(interaction.guild, interaction.user.id)
        except PartyError:
            await interaction.edit_original_response(
                content=notice, embed=home_embed(), view=HomeView(interaction.user.id)
            )
            return
    view = PartyView(interaction.user.id, screen, page)
    await interaction.edit_original_response(
        content=notice,
        embed=view.embed(interaction.guild),
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class PartySelect(discord.ui.Select):
    def __init__(self, parties, guild):
        super().__init__(
            placeholder="参加するパーティーを選択",
            options=[
                discord.SelectOption(
                    label=f"{member_name(guild, party.leader_id)}さんのパーティー"[
                        :100
                    ],
                    value=party.id,
                    description=f"{len(party.members)}人・参加募集中",
                )
                for party in parties
            ],
        )

    async def callback(self, interaction):
        await self.view.act(interaction, "join", self.values[0])


class PartyView(BaseView):
    def __init__(self, owner_id, screen, page=0):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.screen = screen
        self.busy = False
        count = len(screen.own.members) if screen.own else len(screen.parties)
        self.page_count = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(page, self.page_count - 1))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page + 1 >= self.page_count
        if self.page_count == 1:
            self.remove_item(self.previous)
            self.remove_item(self.next_page)
        if screen.own:
            self.remove_item(self.create)
            if screen.own.leader_id != owner_id:
                self.remove_item(self.disband)
        else:
            self.remove_item(self.leave)
            self.remove_item(self.disband)
            self.create.disabled = screen.channel_id is None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True

    def embed(self, guild):
        screen = self.screen
        embed = discord.Embed(title="🤝 パーティーを組む", color=discord.Color.green())
        if screen.channel_id is None:
            embed.description = "パーティーを組むにはVCに参加してください。\n参加したら「更新」を押してください。"
        elif screen.own:
            party = screen.own
            embed.title = f"🤝 {member_name(guild, party.leader_id)}さんのパーティー"
            state = (
                "パーティー成立・参加募集中"
                if len(party.members) >= 2
                else "仲間を募集中（あと1人で成立）"
            )
            people = party.members[self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE]
            embed.description = (
                f"VC：<#{party.channel_id}>\n{state} · {len(party.members)}人\n\n"
                + "\n".join(
                    f"{'👑' if uid == party.leader_id else '👤'} {member_name(guild, uid)}"
                    for uid in people
                )
            )
            embed.description += "\n\n同じVCの仲間がトップ画面から参加できます。\nVCを退出・移動すると自動で脱退します。"
        else:
            parties = screen.parties[
                self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE
            ]
            embed.description = f"現在のVC：<#{screen.channel_id}>\n\n"
            if parties:
                embed.description += (
                    "参加するパーティーを選んでください。\n\n"
                    + "\n".join(
                        f"👑 {member_name(guild, p.leader_id)}さんのパーティー — {len(p.members)}人"
                        for p in parties
                    )
                )
                if not any(isinstance(item, PartySelect) for item in self.children):
                    self.add_item(PartySelect(parties, guild))
            else:
                embed.description += "募集中のパーティーはありません。\n「パーティーを作成」で仲間を募集しましょう。"
        embed.set_footer(
            text=f"{self.page + 1}/{self.page_count}ページ · 更新で最新の状態を表示 · 共同探索・特典は今後追加予定"
        )
        return embed

    async def act(self, interaction, action="refresh", party_id=None, page=0):
        if self.busy:
            await interaction.response.send_message(
                "処理中です。少しお待ちください。", ephemeral=True
            )
            return
        self.busy = True
        try:
            await interaction.response.defer()
            await show_party_screen(interaction, action, party_id, page)
        finally:
            self.busy = False

    @discord.ui.button(
        label="パーティーを作成", style=discord.ButtonStyle.success, row=1
    )
    async def create(self, interaction, button):
        await self.act(interaction, "create")

    @discord.ui.button(label="更新", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction, button):
        await self.act(interaction, page=self.page)

    @discord.ui.button(label="脱退する", style=discord.ButtonStyle.secondary, row=1)
    async def leave(self, interaction, button):
        await self.act(interaction, "leave", self.screen.own.id)

    @discord.ui.button(label="解散する", style=discord.ButtonStyle.danger, row=1)
    async def disband(self, interaction, button):
        await self.act(interaction, "disband", self.screen.own.id)

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            content=None, embed=home_embed(), view=HomeView(self.owner_id)
        )

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction, button):
        await self.act(interaction, page=self.page - 1)

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction, button):
        await self.act(interaction, page=self.page + 1)
