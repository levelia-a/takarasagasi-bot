"""確定後の難易度選択と、VCチャットの全員共通探索パネル。"""

import logging
from typing import ClassVar

import discord

from services.party_exploration_service import PartyExplorationService
from services.party_service import PartyError
from services.settings_service import SettingsService
from services.treasure_catalog_service import TreasureCatalogError
from views.common import BaseView
from views.messages import exploration_embed, map_start_embed, treasure_panel
from views.treasure_inventory import show_treasure_list

logger = logging.getLogger(__name__)


class PartyDifficultyView(BaseView):
    def __init__(self, owner_id, party):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.party = party
        for button in (self.beginner, self.intermediate, self.advanced, self.reform):
            button.disabled = owner_id != party.leader_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "この画面は開いた本人だけが操作できます。", ephemeral=True
            )
            return False
        return True

    async def embed(self, guild):
        embed = treasure_panel(await SettingsService.get_all())
        embed.title = "🤝 パーティーの難易度選択"
        embed.description = (
            f"VC：<#{self.party.channel_id}>\n参加者：{len(self.party.members)}人\n"
            f"リーダー：<@{self.party.leader_id}>\n\n"
            "リーダーが全員分の難易度を選んでください。\n"
            "全員が解放済みの難易度で開始できます。\n"
            "同じ地図・成否・宝物を共有し、結果は各メンバーに記録します。\n"
            "探索画面はVCのチャットに表示します。\n"
            "探索中の退出・移動・脱退で共有探索は終了し、未確定の宝物は受け取れません。"
        )
        return embed

    async def start(self, interaction, difficulty):
        await interaction.response.defer()
        try:
            channel = interaction.guild.get_channel(self.party.channel_id)
            permissions = (
                channel.permissions_for(interaction.guild.me) if channel else None
            )
            if permissions is None or not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
            ):
                raise PartyError(
                    "VCのチャットに探索画面を送れません。Botに「チャンネルを見る」「メッセージを送信」「埋め込みリンク」の権限が必要です。"
                )
            run = await PartyExplorationService.create(
                interaction.guild,
                interaction.user.id,
                self.party.id,
                self.party.confirmation_id,
                difficulty,
            )
        except (PartyError, TreasureCatalogError) as error:
            await interaction.followup.send(
                str(error),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        view = SharedExplorationView(run)
        view.busy = True
        try:
            message = await channel.send(
                embed=shared_embed(run),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except BaseException:
            await PartyExplorationService.abort(
                interaction.guild,
                run,
                "探索画面を送信できなかったため開始を取り消しました。",
            )
            view.stop()
            raise
        view.message = message
        SharedExplorationView.active[run.id] = view
        run.message_url = message.jump_url
        try:
            await interaction.edit_original_response(
                content=f"共有探索を開始しました。\n{message.jump_url}",
                embed=None,
                view=None,
            )
            await PartyExplorationService.step(
                interaction.guild, run, interaction.user.id, True, 0
            )
            await update_shared_message(run)
        finally:
            # 保存・表示失敗時も同じ抽選結果を再試行できるよう操作を戻す。
            view.busy = False

    @discord.ui.button(
        label="初級宝探し", emoji="🟢", style=discord.ButtonStyle.success
    )
    async def beginner(self, interaction, button):
        await self.start(interaction, "beginner")

    @discord.ui.button(
        label="中級宝探し", emoji="🔵", style=discord.ButtonStyle.primary
    )
    async def intermediate(self, interaction, button):
        await self.start(interaction, "intermediate")

    @discord.ui.button(label="上級宝探し", emoji="🔴", style=discord.ButtonStyle.danger)
    async def advanced(self, interaction, button):
        await self.start(interaction, "advanced")

    @discord.ui.button(
        label="パーティーを組み直す", style=discord.ButtonStyle.secondary, row=1
    )
    async def reform(self, interaction, button):
        from views.party import show_party_screen

        await interaction.response.defer()
        await show_party_screen(
            interaction,
            "reform",
            self.party.id,
            confirmation_id=self.party.confirmation_id,
        )

    @discord.ui.button(label="更新", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction, button):
        from views.party import show_party_screen

        await interaction.response.defer()
        await show_party_screen(interaction)


def shared_embed(run):
    if run.aborted:
        return discord.Embed(
            title="🤝 共有探索を終了しました",
            description=run.aborted,
            color=discord.Color.orange(),
        )
    embed = (
        exploration_embed(run.session)
        if run.session.exploration_count
        else map_start_embed(run.session)
    )
    embed.title = f"🤝 {embed.title}"
    embed.add_field(
        name="パーティー探索",
        value=f"👑 リーダー：<@{run.leader_id}>\n参加者：{len(run.participants)}人\n操作はリーダー専用です。",
        inline=False,
    )
    embed.set_footer(
        text="全員同じ探索結果 · 報酬・探索回数は各メンバーに記録 · VC退出・移動で共有探索終了"
    )
    return embed


async def update_shared_message(run):
    old = SharedExplorationView.active.get(run.id)
    if old is None or old.message is None:
        return
    view = SharedExplorationView(run)
    view.message = old.message
    try:
        await old.message.edit(
            content=None,
            embed=shared_embed(run),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except BaseException:
        view.stop()
        raise
    old.stop()
    SharedExplorationView.active[run.id] = view


async def refresh_invalid_runs(guild):
    for run in await PartyExplorationService.expire_invalid(guild):
        try:
            await update_shared_message(run)
        except discord.HTTPException:
            logger.exception("共有探索の終了画面更新に失敗: run=%s", run.id)


class SharedExplorationView(BaseView):
    active: ClassVar[dict[str, "SharedExplorationView"]] = {}

    def __init__(self, run):
        super().__init__(timeout=300)
        self.run = run
        self.version = run.version
        self.message = None
        self.busy = False
        if run.complete or run.aborted:
            self.remove_item(self.deeper)
            self.remove_item(self.retreat)

    async def interaction_check(self, interaction):
        if interaction.user.id not in self.run.user_ids:
            await interaction.response.send_message(
                "この探索のパーティーメンバーだけが操作できます。", ephemeral=True
            )
            return False
        return True

    async def act(self, interaction, deeper):
        if interaction.user.id != self.run.leader_id:
            await interaction.response.send_message(
                "探索を進められるのはリーダーだけです。", ephemeral=True
            )
            return
        if self.busy:
            await interaction.response.send_message(
                "処理中です。少しお待ちください。", ephemeral=True
            )
            return
        self.busy = True
        try:
            await interaction.response.defer()
            try:
                await PartyExplorationService.step(
                    interaction.guild,
                    self.run,
                    interaction.user.id,
                    deeper,
                    self.version,
                )
            except PartyError as error:
                await interaction.followup.send(str(error), ephemeral=True)
            await update_shared_message(self.run)
        finally:
            self.busy = False

    @discord.ui.button(label="さらに奥へ", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def deeper(self, interaction, button):
        await self.act(interaction, True)

    @discord.ui.button(label="引き返す", emoji="🏠", style=discord.ButtonStyle.success)
    async def retreat(self, interaction, button):
        await self.act(interaction, False)

    @discord.ui.button(
        label="宝物一覧", emoji="🎒", style=discord.ButtonStyle.secondary
    )
    async def inventory(self, interaction, button):
        if self.run.pending:
            await interaction.response.send_message(
                "探索結果を保存中です。保存が完了してから確認してください。",
                ephemeral=True,
            )
            return
        await show_treasure_list(
            interaction,
            interaction.user.id,
            self.run.session.found_treasures,
            bool(self.run.aborted) or self.run.session.result == "failure",
        )

    async def on_timeout(self):
        if SharedExplorationView.active.get(self.run.id) is not self:
            return
        if self.message is not None:
            ended = await PartyExplorationService.abort(
                self.message.guild,
                self.run,
                "操作期限が切れたため共有探索を終了しました。宝物は確定していません。",
                expected_version=self.version,
            )
            if not ended or SharedExplorationView.active.get(self.run.id) is not self:
                return
            try:
                await self.message.edit(embed=shared_embed(self.run), view=None)
            except discord.HTTPException:
                pass
        SharedExplorationView.active.pop(self.run.id, None)
        PartyExplorationService.runs.pop(self.run.id, None)
