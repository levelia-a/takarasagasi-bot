"""宝探し履歴を10件ずつ閲覧する管理者専用画面。"""

import asyncio

import discord

from services.admin_service import AdminService
from views.common import AdminOnlyView
from views.messages import RESULT_NAMES


def history_embed(rows, page):
    embed = discord.Embed(title="📜 宝探し履歴", color=discord.Color.gold())
    if not rows:
        embed.description = "まだ履歴はありません。"
    for row in rows:
        # 最大長のユーザー名・65桁の金額でも10件をDiscordの制限内に収める。
        name = row['user_name']
        name = name[:80] + ('…' if len(name) > 80 else '')
        embed.add_field(
            name=discord.utils.escape_markdown(name) + (' 🧪' if row['is_test'] else ''),
            value=(
                f"<@{row['user_id']}> / {row['difficulty']}\n"
                f"開始：{row['start_price']:,} LIA\n"
                f"成功：{row['success_count']}回 / 結果：{RESULT_NAMES.get(row['result'], row['result'])}\n"
                f"報酬：{row['final_reward']:,} LIA\n{row['created_at']}"
            ),
            inline=False,
        )
    embed.set_footer(text=f"{page + 1}ページ目・{len(rows)}件｜新しい順・1ページ10件")
    return embed


class HistoryView(AdminOnlyView):
    def __init__(self, user_id, rows, has_next):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.pages = [(rows, has_next)]
        self.page = 0
        self.lock = asyncio.Lock()
        self.message = None
        self.update_buttons()

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この履歴画面は開いた本人だけが操作できます。", ephemeral=True)
            return False
        return True

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next.disabled = not self.pages[self.page][1]

    async def turn_page(self, interaction, step):
        await interaction.response.defer()
        async with self.lock:
            target = self.page + step
            if target < 0 or (step > 0 and not self.pages[self.page][1]):
                return
            if target == len(self.pages):
                rows, has_next = await AdminService.history_page(self.pages[self.page][0][-1]['id'])
                if not rows:
                    # 閲覧中にテスト履歴が削除され、続きがなくなった場合。
                    self.pages[self.page] = (self.pages[self.page][0], False)
                    self.update_buttons()
                    await interaction.edit_original_response(view=self)
                    return
                self.pages.append((rows, has_next))
            previous = self.page
            self.page = target
            self.update_buttons()
            try:
                await interaction.edit_original_response(
                    embed=history_embed(self.pages[target][0], target), view=self,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except BaseException:
                self.page = previous
                self.update_buttons()
                raise

    @discord.ui.button(label="前へ", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.turn_page(interaction, -1)

    @discord.ui.button(label="次へ", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        await self.turn_page(interaction, 1)

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


async def show_history(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    rows, has_next = await AdminService.history_page()
    view = HistoryView(interaction.user.id, rows, has_next)
    view.message = await interaction.edit_original_response(
        embed=history_embed(rows, 0), view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )
