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


async def show_party_screen(
    interaction,
    action="refresh",
    party_id=None,
    page=0,
    confirmation_id=None,
    expected_members=None,
):
    notice = None
    try:
        screen = await PartyService.run(
            interaction.guild,
            interaction.user.id,
            action,
            party_id,
            confirmation_id,
            expected_members,
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
    from views.party_exploration import PartyDifficultyView, refresh_invalid_runs

    if action != "refresh":
        await refresh_invalid_runs(interaction.guild)
    if screen.own and screen.own.confirmation_id and not screen.own.run_id:
        view = PartyDifficultyView(interaction.user.id, screen.own)
        embed = await view.embed(interaction.guild)
    else:
        view = PartyView(interaction.user.id, screen, page)
        embed = view.embed(interaction.guild)
    await interaction.edit_original_response(
        content=notice,
        embed=embed,
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
                self.remove_item(self.confirm)
            elif screen.own.run_id:
                self.remove_item(self.confirm)
            else:
                self.confirm.disabled = len(screen.own.members) < 2
        else:
            self.remove_item(self.confirm)
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
            if party.run_id:
                from services.party_exploration_service import PartyExplorationService

                run = PartyExplorationService.runs.get(party.run_id)
                embed.description = f"VC：<#{party.channel_id}>\n共有探索中です。\nリーダー：<@{party.leader_id}>"
                if run and run.message_url:
                    embed.description += (
                        f"\n\n[全員共通の探索画面を開く]({run.message_url})"
                    )
                else:
                    embed.description += "\n画面の準備中、またはBotの再起動後です。再起動後は最大5分で再募集できます。"
                embed.description += "\n\n脱退・解散すると全員の共有探索が終了します。"
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
                    available = [
                        p for p in parties if not p.confirmation_id and not p.run_id
                    ]
                    if available:
                        self.add_item(PartySelect(available, guild))
            else:
                embed.description += "募集中のパーティーはありません。\n「パーティーを作成」で仲間を募集しましょう。"
        embed.set_footer(
            text=f"{self.page + 1}/{self.page_count}ページ · リーダーが確定すると難易度選択へ · 更新で最新の状態を表示"
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
            await show_party_screen(
                interaction,
                action,
                party_id,
                page,
                expected_members=self.screen.own.members
                if action == "confirm"
                else None,
            )
        finally:
            self.busy = False

    @discord.ui.button(label="確定", style=discord.ButtonStyle.primary, row=0)
    async def confirm(self, interaction, button):
        await self.act(interaction, "confirm", self.screen.own.id)

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
