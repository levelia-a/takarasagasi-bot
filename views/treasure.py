import asyncio

import discord

from consts.treasure import DIFFICULTIES
from repositories.active_exploration_repository import TreasureSessionExpired
from services.progress_service import DifficultyLocked, ProgressService
from services.treasure_catalog_service import TreasureCatalogError
from services.treasure_service import (
    TreasureAlreadyActive,
    TreasureService,
    TreasureStopped,
)
from views.common import BaseView
from views.messages import exploration_text
from views.treasure_inventory import TreasureResultView, show_treasure_list


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
            if deeper or self.session.exploration_count == 0:
                await interaction.edit_original_response(
                    content="🔎 **さらに奥を探索中……**", view=self
                )
                await asyncio.sleep(1.5)
                await TreasureService.explore(self.session)
            else:
                await TreasureService.retreat(self.session)
            await self.show_result(interaction)
        except TreasureSessionExpired as error:
            await interaction.edit_original_response(content=f"⌛ {error}", view=None)
            self.stop()
        finally:
            self.busy = False

    async def show_result(self, interaction):
        """表示成功後にViewを止める。Discordエラー時は同じsessionで再操作できる。"""
        finished = self.session.result is not None
        display_view = TreasureResultView(self.session) if finished else self
        self.message = await interaction.edit_original_response(
            content=exploration_text(self.session), view=display_view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        display_view.message = self.message
        if finished:
            self.stop()
        try:
            if self.session.unlocked_difficulty:
                await ProgressService.mark_unlock_notification(
                    self.session.user_id, self.session.unlocked_difficulty
                )
                self.session.unlocked_difficulty = None
        finally:
            # 通知済み保存の失敗で、終了済みゲームの開始枠を残さない。
            if finished:
                await TreasureService.release_user(
                    self.session.user_id, self.session.id
                )

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

    @discord.ui.button(label="宝物一覧", emoji="🎒", style=discord.ButtonStyle.secondary)
    async def inventory(self, interaction, button):
        await show_treasure_list(
            interaction, self.session.user_id, self.session.found_treasures,
            self.session.result == "failure",
        )

    async def on_timeout(self):
        """操作期限が切れた画面からボタンを取り除き、開始ロックを解放する。"""
        await TreasureService.release_user(self.session.user_id, self.session.id)
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
        except (TreasureStopped, TreasureAlreadyActive, TreasureCatalogError) as error:
            await interaction.edit_original_response(content=f"🔴 {error}")
            return
        # 難易度解放システム：未解放なら本人だけに現在の進捗を表示する。
        except DifficultyLocked as error:
            await interaction.edit_original_response(content=str(error))
            return
        view = ExplorationView(session)
        # 初回処理もボタン操作と同じbusyで守り、先行撤退や二重探索を防ぐ。
        view.busy = True
        view_attached = False
        try:
            config = DIFFICULTIES[difficulty]
            await interaction.edit_original_response(
                content=f"{config['emoji']} **{config['name']}宝探し**\n\n🗺️ 宝の地図を手に入れた！\n\n💰 必要LIA：**{session.price:,} LIA**"
            )
            await asyncio.sleep(1)
            message = await interaction.edit_original_response(
                content="🔎 **探索中……**", view=view
            )
            view.message = message
            view_attached = True
            await asyncio.sleep(1.5)
            await TreasureService.explore(session)
            await view.show_result(interaction)
        except TreasureSessionExpired as error:
            await interaction.edit_original_response(content=f"⌛ {error}", view=None)
            view.stop()
        except BaseException:
            # Viewを表示する前の失敗だけ開始枠を解放する。
            # 初回探索開始後は同じsession/pending IDで再操作できる状態を残す。
            if not view_attached:
                view.stop()
                await TreasureService.release_user(session.user_id, session.id)
            raise
        finally:
            view.busy = False

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
