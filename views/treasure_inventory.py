"""探索やDB保存を行わない、本人向けの宝物一覧。"""

import discord

from views.common import BaseView
from views.messages import treasure_pages


class TreasureOwnerView(BaseView):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ この宝物一覧はあなたのものではありません。", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class TreasureListView(TreasureOwnerView):
    def __init__(self, user_id, pages):
        super().__init__(user_id)
        self.pages = pages
        self.page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == len(self.pages) - 1

    async def turn_page(self, interaction, step):
        self.page = min(max(self.page + step, 0), len(self.pages) - 1)
        self.update_buttons()
        await interaction.response.edit_message(content=self.pages[self.page], view=self, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.turn_page(interaction, -1)

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        await self.turn_page(interaction, 1)


async def show_treasure_list(interaction, user_id, found_treasures, lost):
    # クリック時点のスナップショット。閲覧中に探索が進んでもページ内容は変えない。
    pages = treasure_pages(tuple(found_treasures), lost)
    view = TreasureListView(user_id, pages) if len(pages) > 1 else None
    await interaction.response.send_message(pages[0], view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    if view:
        view.message = await interaction.original_response()


class TreasureResultView(TreasureOwnerView):
    def __init__(self, session):
        super().__init__(session.user_id)
        self.found_treasures = tuple(session.found_treasures)
        self.lost = session.result == "failure"

    @discord.ui.button(label="宝物一覧", emoji="🎒", style=discord.ButtonStyle.secondary)
    async def inventory(self, interaction, button):
        await show_treasure_list(interaction, self.user_id, self.found_treasures, self.lost)
