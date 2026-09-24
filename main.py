"""エントリーポイント。DB接続とDiscord Botの起動を管理する。"""

import asyncio
import logging

import discord
from discord.ext import commands

from commands.treasure import TreasureCommands
from commands.ranking import RankingCommands
from config import Config
from services.db_service import DbService
from services.schema_service import SchemaService
from services.settings_service import SettingsService
from views.common import report_error
from views.treasure import TreasureView

logger = logging.getLogger(__name__)


class TreasureBot(commands.Bot):
    def __init__(self, config):
        """Botの基本設定とエラーハンドラーを初期化する。"""
        intents = discord.Intents.default()
        intents.voice_states = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            member_cache_flags=discord.MemberCacheFlags(voice=True, joined=False),
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.config = config
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        """DB接続を開始し、コマンドと常設パネルを登録する。"""
        await DbService.connect(self.config.database)
        await SchemaService.validate_required_tables()
        SettingsService.validate_settings(await SettingsService.get_all())
        await self.add_cog(TreasureCommands())
        await self.add_cog(RankingCommands(self, self.config.ranking_interval_seconds))
        self.add_view(TreasureView())
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info("コマンド同期成功: guild=%s count=%s", guild.id, len(synced))

    async def on_ready(self):
        """Discordへの接続完了をログに出力する。"""
        logger.info("宝探しBot起動成功: %s", self.user)

    async def on_app_command_error(self, interaction, error):
        """スラッシュコマンドのエラーを記録して利用者に通知する。"""
        await report_error(interaction, error)

    async def close(self):
        """BotとDB接続プールを終了する。"""
        try:
            await self.remove_cog("RankingCommands")
            await super().close()
        finally:
            await DbService.close()


async def run():
    """環境変数から設定を読み込み、Botを起動する。"""
    config = Config.from_env()
    async with TreasureBot(config) as bot:
        await bot.start(config.token)


def main():
    """ログを設定し、非同期の起動処理を実行する。"""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
