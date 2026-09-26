"""サーバー退会と、停止中の退会・再参加を定期照合する。"""

import logging

from discord.ext import commands, tasks

from services.guild_service import GuildService

logger = logging.getLogger(__name__)


class GuildEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.reconcile_guilds.start()

    async def cog_unload(self):
        self.reconcile_guilds.cancel()

    @tasks.loop(seconds=60)
    async def reconcile_guilds(self):
        for server in self.bot.guilds:
            if server.unavailable:
                continue
            try:
                await GuildService.reconcile(server)
            except Exception:
                logger.exception("ゲーム内ギルドの照合に失敗: server=%s", server.id)

    @reconcile_guilds.before_loop
    async def before_reconcile(self):
        await self.bot.wait_until_ready()
