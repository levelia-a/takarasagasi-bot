import asyncio
import os
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

from config import DatabaseConfig
from database.tables import TABLES_SQL
from services.db_service import DbService
from services.guild_service import GuildError, GuildService
from services.schema_service import SchemaService
from tests.test_guild import server_fixture


@unittest.skipUnless(
    os.getenv("TAKARA_TEST_MYSQL_URL"), "使い捨てMySQLのURLが未指定です"
)
class GuildMySQLTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.dict(os.environ, {"MYSQL_URL": os.environ["TAKARA_TEST_MYSQL_URL"]}):
            config = DatabaseConfig.from_env()
        await DbService.connect(config)
        self.addAsyncCleanup(DbService.close)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SHOW TABLES")
            if await cursor.fetchall():
                self.fail("空のテスト用DBが必要です。既存テーブルは削除しません。")
        self.addAsyncCleanup(self.cleanup_tables)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for statement in TABLES_SQL.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        self.server = server_fixture()

    async def cleanup_tables(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for table in SchemaService.REQUIRED_TABLES:
                await cursor.execute(f"DROP TABLE IF EXISTS {table}")

    async def create(self, uid=1, password="secret"):
        c = await GuildService.prepare(self.server, uid, "create", password, "仲間")
        return await GuildService.confirm(self.server, uid, c)

    async def join(self, uid, password="secret"):
        c = await GuildService.prepare(self.server, uid, "join", password)
        return await GuildService.confirm(self.server, uid, c)

    async def test_concurrent_last_slot_only_one_wins(self):
        await self.create()
        for uid in range(2, 6):
            await self.join(uid)
        a = await GuildService.prepare(self.server, 6, "join", "secret")
        b = await GuildService.prepare(self.server, 7, "join", "secret")
        results = await asyncio.gather(
            GuildService.confirm(self.server, 6, a),
            GuildService.confirm(self.server, 7, b),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, GuildError) for r in results), 1)
        own = await GuildService.screen(self.server, 1)
        self.assertEqual(len(own.members), 6)

    async def test_concurrent_duplicate_create_and_one_membership(self):
        a = await GuildService.prepare(self.server, 1, "create", "same", "A")
        b = await GuildService.prepare(self.server, 2, "create", "same", "B")
        results = await asyncio.gather(
            GuildService.confirm(self.server, 1, a),
            GuildService.confirm(self.server, 2, b),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, GuildError) for r in results), 1)
        await self.create(3, "other")
        a = await GuildService.prepare(self.server, 4, "join", "same")
        b = await GuildService.prepare(self.server, 4, "join", "other")
        results = await asyncio.gather(
            GuildService.confirm(self.server, 4, a),
            GuildService.confirm(self.server, 4, b),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, GuildError) for r in results), 1)

    async def test_departure_random_leader_then_empty_and_passphrase_reuse(self):
        await self.create()
        await self.join(2)
        await self.join(3)
        del self.server.users[1]
        await GuildService.reconcile(self.server)
        own = await GuildService.screen(self.server, 2)
        self.assertIn(own.leader_id, (2, 3))
        self.assertEqual({m.user_id for m in own.members}, {2, 3})
        del self.server.users[2]
        del self.server.users[3]
        await GuildService.reconcile(self.server)
        new = await self.create(4)
        self.assertEqual(new.leader_id, 4)

    async def test_offline_leave_rejoin_invalidates_old_membership_and_confirmation(
        self,
    ):
        await self.create()
        await self.join(2)
        stale = await GuildService.prepare(self.server, 3, "join", "secret")
        self.server.users[1].joined_at = datetime(2026, 9, 26, tzinfo=timezone.utc)
        await GuildService.reconcile(self.server)
        self.assertIsNone(await GuildService.screen(self.server, 1))
        self.assertEqual((await GuildService.screen(self.server, 2)).leader_id, 2)
        with self.assertRaisesRegex(GuildError, "変わりました"):
            await GuildService.confirm(self.server, 3, stale)
        await self.create(1, "new")
        fresh = await GuildService.prepare(self.server, 3, "join", "new")
        self.server.users[3].joined_at = datetime(2026, 9, 26, tzinfo=timezone.utc)
        with self.assertRaisesRegex(GuildError, "所属が変わりました"):
            await GuildService.confirm(self.server, 3, fresh)

    async def test_retry_is_idempotent_and_failed_save_rolls_back(self):
        c = await GuildService.prepare(self.server, 1, "create", "secret", "仲間")
        await GuildService.confirm(self.server, 1, c)
        await GuildService.confirm(self.server, 1, c)
        join = await GuildService.prepare(self.server, 2, "join", "secret")
        from repositories.guild_repository import GuildRepository

        original = GuildRepository.save

        async def fail_after_write(*args):
            await original(*args)
            if args[2] != args[3]:
                raise RuntimeError("simulated write failure")

        with (
            patch.object(GuildRepository, "save", side_effect=fail_after_write),
            self.assertRaises(RuntimeError),
        ):
            await GuildService.confirm(self.server, 2, join)
        self.assertIsNone(await GuildService.screen(self.server, 2))
        await GuildService.confirm(self.server, 2, join)
        await GuildService.confirm(self.server, 2, join)
        self.assertEqual(len((await GuildService.screen(self.server, 1)).members), 2)

    async def test_migration_is_repeatable_and_schema_validated(self):
        from pathlib import Path

        sql = Path("src/sql/20260926_game_guilds.sql").read_text()
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for statement in sql.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        await SchemaService.validate_required_tables()
        c = await GuildService.prepare(self.server, 1, "create", "secret", "仲間")
        with self.assertRaises(GuildError):
            await GuildService.confirm(self.server, 1, replace(c, expires_at=0))

    async def test_discord_failure_preserves_membership(self):
        from types import SimpleNamespace

        import discord

        await self.create()
        self.server.fetch_member.side_effect = discord.HTTPException(
            SimpleNamespace(status=503, reason="Unavailable"), "temporary failure"
        )
        with self.assertLogs("services.guild_service", level="WARNING"):
            await GuildService.reconcile(self.server)
        async with GuildService.transaction(self.server.id) as guilds:
            self.assertEqual(len(GuildService.own(guilds, 1).members), 1)

    async def test_old_reconcile_snapshot_cannot_remove_new_guild(self):
        first = await self.create()
        old_member = first.members[0]
        self.server.users[1].joined_at = datetime(2026, 9, 26, tzinfo=timezone.utc)
        await GuildService.reconcile(self.server)
        new = await self.create(1, "new")
        async with GuildService.transaction(self.server.id) as guilds:
            GuildService.remove_member(guilds, first.id, old_member)
        self.assertEqual((await GuildService.screen(self.server, 1)).id, new.id)
