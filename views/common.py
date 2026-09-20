import logging

import discord

logger = logging.getLogger(__name__)


async def require_admin(interaction):
    """管理者権限を確認し、権限がなければエラーを返信する。"""
    if (
        interaction.guild is None
        or not interaction.user.guild_permissions.administrator
    ):
        await interaction.response.send_message(
            "❌ 管理者のみ使用できます。", ephemeral=True
        )
        return False
    return True


async def report_error(interaction, error):
    """例外をログに記録し、利用者にエラーメッセージを返信する。"""
    logger.error(
        "Discord操作の処理に失敗: guild=%s user=%s",
        interaction.guild_id,
        interaction.user.id,
        exc_info=(type(error), error, error.__traceback__),
    )
    text = "❌ 処理中にエラーが発生しました。管理者にお問い合わせください。"
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


class BaseView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        """ボタンなどの操作中に発生した例外を共通処理に渡す。"""
        await report_error(interaction, error)


class AdminOnlyView(BaseView):
    async def interaction_check(self, interaction):
        """管理者だけにViewの操作を許可する。"""
        return await require_admin(interaction)


class AdminOnlyModal(discord.ui.Modal):
    async def interaction_check(self, interaction):
        """管理者だけにモーダルの送信を許可する。"""
        return await require_admin(interaction)

    async def on_error(self, interaction, error):
        """モーダル処理中に発生した例外を共通処理に渡す。"""
        await report_error(interaction, error)


async def send_pages(interaction, entries):
    """履歴10件がDiscordの文字数制限を超えても表示する。"""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    page = ""
    for entry in entries:
        # 長い管理ログも切り捨てずに分割する。
        while entry:
            size = min(len(entry), 1900 - len(page))
            page += entry[:size]
            entry = entry[size:]
            if len(page) == 1900:
                await interaction.followup.send(
                    page,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                page = ""
    if page:
        await interaction.followup.send(
            page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )
