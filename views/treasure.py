import asyncio

import discord

from consts.treasure import DIFFICULTIES
from services.treasure_service import TreasureService, TreasureStopped
from views.common import BaseView
from views.messages import exploration_text


class ExplorationView(BaseView):
    def __init__(self, session):
        """進行中の探索と操作ボタンを初期化する。"""
        super().__init__(timeout=300)
        self.session = session
        self.busy = False
        self.message = None

    async def interaction_check(self, interaction):
        """探索を開始した本人だけにボタン操作を許可する。"""
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "❌ この宝探しはあなたのものではありません。", ephemeral=True
            )
            return False
        return True

    async def act(self, interaction, deeper):
        """連打を防ぎながら探索または撤退を実行し、画面を更新する。"""
        if self.busy:
            await interaction.response.send_message(
                "⏳ 処理中です。少しお待ちください。", ephemeral=True
            )
            return
        self.busy = True
        try:
            await interaction.response.defer()
            if deeper:
                await interaction.edit_original_response(
                    content="🔎 **さらに奥を探索中……**", view=self
                )
                await asyncio.sleep(1.5)
                await TreasureService.explore(self.session)
            else:
                await TreasureService.retreat(self.session)
            if self.session.result is not None:
                self.stop()
                view = None
            else:
                view = self
            await interaction.edit_original_response(
                content=exploration_text(self.session), view=view
            )
        finally:
            self.busy = False

    @discord.ui.button(
        label="さらに奥へ",
        emoji="⚔️",
        style=discord.ButtonStyle.danger,
        custom_id="takara_deeper",
    )
    async def deeper(self, interaction, button):
        """さらに奥へ進むボタンのクリックを処理する。"""
        await self.act(interaction, True)

    @discord.ui.button(
        label="引き返す",
        emoji="🏠",
        style=discord.ButtonStyle.success,
        custom_id="takara_retreat",
    )
    async def retreat(self, interaction, button):
        """引き返すボタンのクリックを処理する。"""
        await self.act(interaction, False)

    async def on_timeout(self):
        """操作期限が切れた画面からボタンを取り除く。"""
        if self.message is not None:
            try:
                await self.message.edit(
                    content="⌛ 操作期限が切れました。宝探しパネルから開始し直してください。",
                    view=None,
                )
            except discord.HTTPException:
                pass


class TreasureView(BaseView):
    def __init__(self):
        """再起動後も使用する宝探しの入口パネルを初期化する。"""
        super().__init__(timeout=None)

    async def start(self, interaction, difficulty):
        """選択した難易度の探索を開始し、最初の結果を本人に表示する。"""
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            session = await TreasureService.create(
                interaction.user.id, str(interaction.user), difficulty
            )
        except TreasureStopped as error:
            await interaction.edit_original_response(content=f"🔴 {error}")
            return
        config = DIFFICULTIES[difficulty]
        await interaction.edit_original_response(
            content=f"{config['emoji']} **{config['name']}宝探し**\n\n🗺️ 宝の地図を手に入れた！\n\n💰 必要LIA：**{session.price:,} LIA**"
        )
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="🔎 **探索中……**")
        await asyncio.sleep(1.5)
        await TreasureService.explore(session)
        view = ExplorationView(session) if session.result is None else None
        message = await interaction.edit_original_response(
            content=exploration_text(session), view=view
        )
        if view:
            view.message = message

    @discord.ui.button(
        label="初級宝探し",
        emoji="🟢",
        style=discord.ButtonStyle.success,
        custom_id="takara_beginner",
    )
    async def beginner(self, interaction, button):
        """初級宝探しボタンから探索を開始する。"""
        await self.start(interaction, "beginner")

    @discord.ui.button(
        label="中級宝探し",
        emoji="🔵",
        style=discord.ButtonStyle.primary,
        custom_id="takara_intermediate",
    )
    async def intermediate(self, interaction, button):
        """中級宝探しボタンから探索を開始する。"""
        await self.start(interaction, "intermediate")

    @discord.ui.button(
        label="上級宝探し",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="takara_advanced",
    )
    async def advanced(self, interaction, button):
        """上級宝探しボタンから探索を開始する。"""
        await self.start(interaction, "advanced")
