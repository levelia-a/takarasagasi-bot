import asyncio
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from services.guild_service import (
    GameGuild,
    GuildConfirmation,
    GuildError,
    GuildMember,
    GuildService,
)
from tests.test_views import interaction
from views.guild import GuildConfirmView, GuildModal, GuildView
from views.home import HomeView


def member(uid):
    return GuildMember(uid, "2026-09-01T00:00:00+00:00")


def game_guild(gid="g", users=(1,), password="secret"):
    return GameGuild(
        gid,
        "仲間",
        GuildService.passphrase_hash(password),
        users[0],
        tuple(member(u) for u in users),
    )


def confirmation(guild=None, uid=2, action="join"):
    return GuildConfirmation(
        action,
        uid,
        100,
        member(uid).server_joined_at,
        guild or game_guild(),
        time.monotonic() + 300,
    )


def server_fixture():
    users = {
        i: SimpleNamespace(
            id=i, bot=False, joined_at=datetime(2026, 9, 1, tzinfo=timezone.utc)
        )
        for i in range(1, 15)
    }

    async def fetch(uid):
        if uid not in users:
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"), {"code": 10007}
            )
        return users[uid]

    return SimpleNamespace(
        id=100,
        unavailable=False,
        fetch_member=AsyncMock(side_effect=fetch),
        users=users,
    )


class GuildRulesTests(unittest.TestCase):
    def test_membership_cap_and_idempotent_join(self):
        target = game_guild(users=(1, 2, 3, 4, 5))
        guilds = {target.id: target}
        c = confirmation(target, 6)
        GuildService.apply_confirmation(guilds, c, member(6))
        GuildService.apply_confirmation(guilds, c, member(6))
        self.assertEqual(len(guilds[target.id].members), 6)
        with self.assertRaisesRegex(GuildError, "満員"):
            GuildService.apply_confirmation(guilds, confirmation(target, 7), member(7))
        other = game_guild("other", (8,), "other")
        guilds[other.id] = other
        with self.assertRaisesRegex(GuildError, "別のギルド"):
            GuildService.apply_confirmation(guilds, confirmation(other, 6), member(6))

    def test_duplicate_passphrase_and_changed_leader(self):
        target = game_guild(users=(1, 2))
        guilds = {target.id: target}
        new = game_guild("new", (3,))
        with self.assertRaisesRegex(GuildError, "使用済み"):
            GuildService.apply_confirmation(
                guilds, confirmation(new, 3, "create"), member(3)
            )
        guilds[target.id] = replace(target, leader_id=2)
        with self.assertRaisesRegex(GuildError, "変わりました"):
            GuildService.apply_confirmation(guilds, confirmation(target, 3), member(3))
        del guilds[target.id]
        with self.assertRaises(GuildError):
            GuildService.apply_confirmation(guilds, confirmation(target, 3), member(3))

    def test_random_successor_empty_cleanup_and_stale_removal(self):
        target = game_guild(users=(1, 2, 3))
        guilds = {target.id: target}
        with patch(
            "services.guild_service.secrets.choice", return_value=member(3)
        ) as choice:
            GuildService.remove_member(guilds, target.id, member(1))
        choice.assert_called_once_with((member(2), member(3)))
        self.assertEqual(guilds[target.id].leader_id, 3)
        GuildService.remove_member(
            guilds, target.id, replace(member(2), server_joined_at="stale")
        )
        self.assertEqual(len(guilds[target.id].members), 2)
        GuildService.remove_member(guilds, target.id, member(2))
        GuildService.remove_member(guilds, target.id, member(3))
        self.assertEqual(guilds, {})

    def test_passphrase_normalization_and_validation(self):
        self.assertEqual(
            GuildService.passphrase_hash(" が "),
            GuildService.passphrase_hash("か\u3099"),
        )
        self.assertNotEqual(
            GuildService.passphrase_hash("A"), GuildService.passphrase_hash("a")
        )
        for text in (" ", "a\nb", "a\x00b", "x" * 65):
            with self.assertRaises(GuildError):
                GuildService.passphrase_hash(text)


class GuildViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_and_owned_screen(self):
        event = interaction()
        with patch("views.guild.GuildService.screen", new=AsyncMock(return_value=None)):
            await HomeView().game_guild.callback(event)
        event.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        view = event.edit_original_response.call_args.kwargs["view"]
        self.assertIsInstance(view, GuildView)
        event.user.id = 2
        self.assertFalse(await view.interaction_check(event))
        joined = GuildView(1, True)
        self.assertEqual([x.label for x in joined.children], ["更新", "戻る"])

    async def test_modal_confirmation_is_private_and_no_secret_echo(self):
        event = interaction()
        event.guild = server_fixture()
        modal = GuildModal(1, "join")
        modal.passphrase._value = "secret"
        with patch.object(
            GuildService, "prepare", new=AsyncMock(return_value=confirmation(uid=1))
        ):
            await modal.on_submit(event)
        event.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        payload = event.edit_original_response.call_args.kwargs
        self.assertIn("仲間", payload["embed"].description)
        self.assertIn("原則脱退できません", payload["embed"].description)
        self.assertNotIn("secret", str(payload["embed"].to_dict()))
        self.assertIsInstance(payload["view"], GuildConfirmView)

    async def test_double_confirmation_calls_service_once_and_cancel_blocks_join(self):
        event = interaction()
        view = GuildConfirmView(confirmation(uid=1))
        gate = asyncio.Event()

        async def confirm(*args):
            await gate.wait()
            return game_guild()

        with patch.object(
            GuildService, "confirm", new=AsyncMock(side_effect=confirm)
        ) as call:
            task = asyncio.create_task(view.confirm.callback(event))
            await asyncio.sleep(0)
            await view.confirm.callback(event)
            gate.set()
            await task
            await view.confirm.callback(event)
            call.assert_awaited_once()
        view = GuildConfirmView(confirmation(uid=1))
        with patch("views.guild.show_guild_screen", new=AsyncMock()):
            await view.cancel.callback(event)
        with patch.object(GuildService, "confirm", new=AsyncMock()) as call:
            await view.confirm.callback(event)
            call.assert_not_awaited()

    async def test_expired_foreign_owner_and_wrong_server_fail_before_io(self):
        server = server_fixture()
        for c, uid, sid in [
            (replace(confirmation(), expires_at=0), 2, 100),
            (confirmation(), 3, 100),
            (confirmation(), 2, 200),
        ]:
            server.id = sid
            with self.assertRaises(GuildError):
                await GuildService.confirm(server, uid, c)
        server.fetch_member.assert_not_awaited()

    async def test_unknown_member_only_is_departure(self):
        server = server_fixture()
        del server.users[1]
        self.assertIsNone(await GuildService.current_member(server, 1))
        server.fetch_member.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), {"code": 10004}
        )
        with self.assertRaises(discord.NotFound):
            await GuildService.current_member(server, 1)
