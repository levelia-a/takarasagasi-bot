"""現在のリーダーが、同じパーティーの仲間へ操作権限を引き継ぐ。"""

import discord

from services.party_service import PartyError, PartyService
from views.common import BaseView
from views.party import member_name, show_party_screen

PAGE_SIZE = 25


async def open_leader_transfer(interaction, party_id, page=0):
    try:
        screen = await PartyService.run(interaction.guild, interaction.user.id)
        party = screen.own
        if (
            party is None
            or party.id != party_id
            or party.leader_id != interaction.user.id
        ):
            raise PartyError("現在のリーダーだけが交代先を選べます。")
        if party.run_id:
            raise PartyError("共有探索中はリーダーを交代できません。")
        if len(party.members) < 2:
            raise PartyError("交代できるパーティーメンバーがいません。")
    except PartyError as error:
        await show_party_screen(interaction)
        await interaction.followup.send(str(error), ephemeral=True)
        return
    view = LeaderTransferView(interaction.user.id, party, interaction.guild, page)
    await interaction.edit_original_response(
        content=None,
        embed=discord.Embed(
            title="👑 リーダーを交代",
            description="新しいリーダーを選んでください。選択するとリーダーが交代します。\n"
            "メンバー構成と、難易度選択中の確定状態は維持されます。\n"
            f"\n候補：{len(party.members) - 1}人 · {view.page + 1}/{view.page_count}ページ",
            color=discord.Color.gold(),
        ),
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class LeaderSelect(discord.ui.Select):
    def __init__(self, guild, candidates):
        super().__init__(
            placeholder="新しいリーダーを選択",
            options=[
                discord.SelectOption(
                    label=member_name(guild, uid)[:100],
                    value=str(uid),
                    description=f"@{guild.get_member(uid).name}"[:100]
                    if getattr(guild.get_member(uid), "name", None)
                    else None,
                )
                for uid in candidates
            ],
            row=0,
        )

    async def callback(self, interaction):
        await interaction.response.defer()
        await show_party_screen(
            interaction,
            "transfer_leader",
            self.view.party.id,
            confirmation_id=self.view.party.confirmation_id,
            target_user_id=int(self.values[0]),
        )


class LeaderTransferView(BaseView):
    def __init__(self, owner_id, party, guild, page=0):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.party = party
        candidates = [uid for uid in party.members if uid != party.leader_id]
        self.page_count = max(1, (len(candidates) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(page, self.page_count - 1))
        self.add_item(
            LeaderSelect(
                guild, candidates[self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE]
            )
        )
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page + 1 >= self.page_count
        if self.page_count == 1:
            self.remove_item(self.previous)
            self.remove_item(self.next_page)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await interaction.response.defer()
        await show_party_screen(interaction)

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction, button):
        await interaction.response.defer()
        await open_leader_transfer(interaction, self.party.id, self.page - 1)

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction, button):
        await interaction.response.defer()
        await open_leader_transfer(interaction, self.party.id, self.page + 1)
