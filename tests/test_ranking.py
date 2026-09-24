import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from commands.ranking import RankingCommands, ranking_embeds
from services.ranking_service import RankingEntry, RankingService, RankingSnapshot


class RankingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.snapshot = RankingSnapshot((), datetime.now(timezone.utc))
        self.enterContext(patch.object(RankingService, '_snapshot', self.snapshot))

    async def test_failure_keeps_previous_snapshot(self):
        with patch('services.ranking_service.DbService.get_connection', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                await RankingService.refresh()
        self.assertIs(RankingService.get_snapshot(), self.snapshot)

    async def test_batch_updates_existing_message_and_retries_after_failure(self):
        bot = MagicMock()
        bot.config.guild_id = 1
        channel = MagicMock()
        channel.guild.id = 1
        message = MagicMock()
        message.edit = AsyncMock(side_effect=[RuntimeError('offline'), None])
        channel.get_partial_message.return_value = message
        bot.fetch_channel = AsyncMock(return_value=channel)
        cog = RankingCommands(bot)
        self.assertEqual(cog.refresh_rankings.seconds, 21600)
        with patch.object(RankingService, 'refresh', new_callable=AsyncMock), patch.object(
            RankingService, 'get_panel', new_callable=AsyncMock, return_value=[1, 2, 3]
        ), self.assertLogs('commands.ranking', level='ERROR'):
            await cog.refresh_rankings()
            await cog.refresh_rankings()
        self.assertEqual(message.edit.await_count, 2)
        channel.get_partial_message.assert_called_with(3)
        channel.send.assert_not_called()

    async def test_shutdown_cancels_running_batch(self):
        bot = MagicMock()
        bot.wait_until_ready = AsyncMock(side_effect=lambda: asyncio.sleep(100))
        cog = RankingCommands(bot)
        await cog.cog_load()
        await cog.cog_unload()
        self.assertTrue(cog.refresh_rankings.get_task().done())

    async def test_install_reuses_saved_panel(self):
        bot = MagicMock()
        bot.config.guild_id = 1
        cog = RankingCommands(bot)
        interaction = MagicMock()
        interaction.guild_id = 1
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        cog.update_panel = AsyncMock()
        with patch.object(RankingService, 'get_panel', new_callable=AsyncMock, return_value=[1, 2, 3]):
            await cog.takara_ranking_panel.callback(cog, interaction)
        cog.update_panel.assert_awaited_once_with([1, 2, 3])
        interaction.channel.send.assert_not_called()

    def test_empty_and_large_values_fit_discord_limits(self):
        self.assertIn('初回集計中', ranking_embeds(None, 21600)[0].description)
        self.assertTrue(all('まだ記録' in e.description for e in ranking_embeds(self.snapshot, 21600)))
        snapshot = RankingSnapshot(tuple(
            RankingEntry(1545489116127559682 + i, metric, 10**65 - 1, i + 1)
            for metric in ('successes', 'payout', 'best') for i in range(10)
        ), self.snapshot.updated_at)
        embeds = ranking_embeds(snapshot, 21600)
        self.assertLessEqual(sum(len(e) for e in embeds), 6000)
        self.assertTrue(all(len(e.description) <= 4096 for e in embeds))
