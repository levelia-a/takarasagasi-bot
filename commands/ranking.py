"""ランキングの定期集計と閲覧コマンド。"""

import logging
import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.ranking_service import RankingService
from views.common import require_admin

logger = logging.getLogger(__name__)


def ranking_embeds(snapshot, interval_seconds):
    if snapshot is None:
        return [discord.Embed(
            title="🏆 探索ランキング",
            description="初回集計中です。しばらくしてからもう一度お試しください。",
        )]
    embeds = []
    for metric, title, unit in (
        ("successes", "合計探索成功回数", "回"),
        ("payout", "累計換金額", " LIA"),
        ("best", "一撃最高額", " LIA"),
    ):
        lines = [
            f"**{entry.position}位** <@{entry.user_id}> — {entry.value:,}{unit}"
            for entry in snapshot.entries if entry.metric == metric
        ]
        embed = discord.Embed(
            title=f"🏆 {title} TOP 10",
            description="\n".join(lines) or "まだ記録がありません。",
            color=discord.Color.gold(),
            timestamp=snapshot.updated_at,
        )
        embed.set_footer(text=(
            f"通常プレイの確定結果のみ・{interval_seconds / 3600:g}時間ごとに集計｜最終集計"
        ))
        embeds.append(embed)
    return embeds


class RankingCommands(commands.Cog):
    def __init__(self, bot, interval_seconds=21600):
        self.bot = bot
        self.panel_lock = asyncio.Lock()
        self.interval_seconds = interval_seconds
        self.refresh_rankings.change_interval(seconds=interval_seconds)

    async def cog_load(self):
        RankingService._snapshot = None
        self.refresh_rankings.start()

    async def cog_unload(self):
        task = self.refresh_rankings.get_task()
        self.refresh_rankings.cancel()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    @tasks.loop(seconds=21600)
    async def refresh_rankings(self):
        try:
            await RankingService.refresh()
            async with self.panel_lock:
                panel = await RankingService.get_panel()
                if panel:
                    await self.update_panel(panel)
        except Exception:
            logger.exception("ランキング集計に失敗しました。次回の定期処理で再試行します。")

    @refresh_rankings.before_loop
    async def before_refresh_rankings(self):
        await self.bot.wait_until_ready()

    async def update_panel(self, panel):
        guild_id, channel_id, message_id = panel
        if guild_id != self.bot.config.guild_id:
            raise ValueError("ランキング設置先のサーバーが設定と一致しません。")
        channel = await self.bot.fetch_channel(channel_id)
        if channel.guild.id != guild_id:
            raise ValueError("ランキング設置先のチャンネルが不正です。")
        message = channel.get_partial_message(message_id)
        await message.edit(
            embeds=ranking_embeds(RankingService.get_snapshot(), self.interval_seconds),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="takara_ranking_panel", description="このチャンネルに6時間更新のランキングを設置します")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def takara_ranking_panel(self, interaction: discord.Interaction):
        if not await require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.guild_id != self.bot.config.guild_id:
            await interaction.edit_original_response(content="設定されたサーバーで実行してください。")
            return
        async with self.panel_lock:
            if RankingService.get_snapshot() is None:
                await RankingService.refresh()
            panel = await RankingService.get_panel()
            if panel:
                try:
                    await self.update_panel(panel)
                except discord.NotFound:
                    pass
                else:
                    await interaction.edit_original_response(
                        content=f"既存のランキングを更新しました。https://discord.com/channels/{panel[0]}/{panel[1]}/{panel[2]}"
                    )
                    return
            message = await interaction.channel.send(
                embeds=ranking_embeds(RankingService.get_snapshot(), self.interval_seconds),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await RankingService.save_panel(interaction.guild_id, interaction.channel_id, message.id)
            await interaction.edit_original_response(content=f"ランキングを設置しました。{message.jump_url}")

    @app_commands.command(name="takara_ranking", description="探索成功回数・換金額のランキングを表示します")
    @app_commands.guild_only()
    async def takara_ranking(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embeds=ranking_embeds(RankingService.get_snapshot(), self.interval_seconds),
            allowed_mentions=discord.AllowedMentions.none(),
        )
