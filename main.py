"""エントリーポイント。依存関係を組み立て、Botを起動する。"""

import asyncio
import logging

import discord
from discord.ext import commands

from commands.treasure import TreasureCommands
from config import Config
from repositories.admin_log_repository import AdminLogRepository
from repositories.result_repository import ResultRepository
from repositories.settings_repository import SettingsRepository
from services.admin_service import AdminService
from services.db_service import DbService
from services.settings_service import SettingsService, validate_settings
from services.treasure_service import TreasureService
from views.common import report_error
from views.treasure import TreasureView

logger = logging.getLogger(__name__)


class TreasureBot(commands.Bot):
    def __init__(self, config):
        """Botと各サービスを初期化する。"""
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default(),
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.config = config
        self.db = DbService(config.database)
        settings_repository = SettingsRepository()
        results = ResultRepository()
        logs = AdminLogRepository()
        self.settings = SettingsService(self.db, settings_repository, logs)
        self.treasure = TreasureService(self.db, self.settings, results)
        self.admin = AdminService(self.db, results, logs)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        """DB接続を開始し、コマンドと常設パネルを登録する。"""
        await self.db.connect()
        validate_settings(await self.settings.get_all())
        await self.add_cog(TreasureCommands(self.treasure, self.settings, self.admin))
        self.add_view(TreasureView(self.treasure))
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
            await super().close()
        finally:
            await self.db.close()


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
