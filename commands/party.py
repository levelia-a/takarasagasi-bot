"""VC移動時と再接続後にパーティー所属を照合する。"""

import logging

from discord.ext import commands, tasks

from services.party_service import PartyService
from views.party_exploration import refresh_invalid_runs

logger = logging.getLogger(__name__)


class PartyEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.reconcile_parties.start()

    async def cog_unload(self):
        self.reconcile_parties.cancel()

    async def reconcile_guild(self, guild):
        if guild.unavailable or not self.bot.is_ready():
            return
        try:
            await PartyService.run(guild)
            await refresh_invalid_runs(guild)
        except Exception:
            logger.exception("パーティーのVC照合に失敗: guild=%s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.bot and before.channel != after.channel:
            await self.reconcile_guild(member.guild)

    @commands.Cog.listener()
    async def on_guild_available(self, guild):
        await self.reconcile_guild(guild)

    @tasks.loop(seconds=60)
    async def reconcile_parties(self):
        # 起動直後と定期照合で、停止中の退出・一時的なDB障害からも回復する。
        for guild in self.bot.guilds:
            await self.reconcile_guild(guild)

    @reconcile_parties.before_loop
    async def before_reconcile(self):
        await self.bot.wait_until_ready()
