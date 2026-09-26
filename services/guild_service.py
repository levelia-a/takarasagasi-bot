"""パーティーから独立した永続ギルドと、本人に束縛した参加確認。"""

import hashlib
import logging
import secrets
import time
import unicodedata
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

import discord

from repositories.guild_repository import GuildRepository
from services.db_service import DbService

logger = logging.getLogger(__name__)
MAX_MEMBERS = 6
CONFIRM_SECONDS = 300


class GuildError(ValueError):
    pass


@dataclass(frozen=True)
class GuildMember:
    user_id: int
    server_joined_at: str


@dataclass(frozen=True)
class GameGuild:
    id: str
    name: str
    passphrase_hash: str
    leader_id: int
    members: tuple[GuildMember, ...]


@dataclass(frozen=True)
class GuildConfirmation:
    action: str
    owner_id: int
    server_id: int
    server_joined_at: str
    target: GameGuild
    expires_at: float


class GuildService:
    @staticmethod
    def clean_text(value, label, limit):
        value = unicodedata.normalize("NFC", value).strip()
        if not 1 <= len(value) <= limit or any(
            unicodedata.category(c).startswith("C") for c in value
        ):
            raise GuildError(
                f"{label}は改行・制御文字を含まない1〜{limit}文字で入力してください。"
            )
        return value

    @staticmethod
    def passphrase_hash(value):
        return hashlib.sha256(
            GuildService.clean_text(value, "あいことば", 64).encode()
        ).hexdigest()

    @staticmethod
    def own(guilds, user_id):
        return next(
            (
                g
                for g in guilds.values()
                if any(m.user_id == user_id for m in g.members)
            ),
            None,
        )

    @staticmethod
    @asynccontextmanager
    async def transaction(server_id):
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    await GuildRepository.lock(cursor, server_id)
                    rows, member_rows = await GuildRepository.load(cursor, server_id)
                    before = {
                        r["id"]: GameGuild(
                            r["id"],
                            r["name"],
                            r["passphrase_hash"],
                            r["leader_id"],
                            tuple(
                                GuildMember(m["user_id"], m["server_joined_at"])
                                for m in member_rows
                                if m["game_guild_id"] == r["id"]
                            ),
                        )
                        for r in rows
                    }
                    after = dict(before)
                    yield after
                    await GuildRepository.save(cursor, server_id, before, after)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    @staticmethod
    async def current_member(server, user_id):
        if server is None or server.unavailable:
            raise GuildError(
                "サーバー情報を確認できません。少し待ってからお試しください。"
            )
        try:
            member = await server.fetch_member(user_id)
        except discord.NotFound as error:
            if error.code == 10007:  # Unknown Memberのみを脱退とみなす。
                return None
            raise
        if member.bot or member.joined_at is None:
            raise GuildError("サーバーの参加情報を確認できません。")
        return GuildMember(user_id, member.joined_at.isoformat())

    @staticmethod
    def remove_member(guilds, guild_id, expected):
        guild = guilds.get(guild_id)
        if guild is None or expected not in guild.members:
            return  # API待ちの間に作られた新しい所属を削除しない。
        members = tuple(m for m in guild.members if m != expected)
        if not members:
            del guilds[guild_id]
        else:
            leader = guild.leader_id
            if leader == expected.user_id:
                leader = secrets.choice(members).user_id
            guilds[guild_id] = replace(guild, members=members, leader_id=leader)

    @staticmethod
    async def reconcile(server, user_id=None):
        if server is None or server.unavailable:
            raise GuildError("サーバー情報を確認できません。")
        async with GuildService.transaction(server.id) as guilds:
            targets = (
                list(guilds.values())
                if user_id is None
                else [GuildService.own(guilds, user_id)]
            )
        # Discord通信はDBロックの外で行う。未キャッシュを脱退と誤認しない。
        for guild in filter(None, targets):
            for member in guild.members:
                try:
                    current = await GuildService.current_member(server, member.user_id)
                    if current != member:
                        async with GuildService.transaction(server.id) as latest:
                            GuildService.remove_member(latest, guild.id, member)
                except (discord.HTTPException, GuildError):
                    if user_id is not None:
                        raise
                    logger.warning(
                        "ギルド所属照合を保留: server=%s user=%s",
                        server.id,
                        member.user_id,
                    )

    @staticmethod
    async def screen(server, user_id):
        await GuildService.reconcile(server, user_id)
        async with GuildService.transaction(server.id) as guilds:
            return GuildService.own(guilds, user_id)

    @staticmethod
    async def prepare(server, user_id, action, passphrase, name=None):
        if action not in ("create", "join"):
            raise ValueError("Unknown guild action")
        digest = GuildService.passphrase_hash(passphrase)
        if action == "create":
            name = GuildService.clean_text(name, "ギルド名", 32)
        await GuildService.reconcile(server, user_id)
        member = await GuildService.current_member(server, user_id)
        if member is None:
            raise GuildError("サーバーに参加している人だけが操作できます。")
        async with GuildService.transaction(server.id) as guilds:
            if GuildService.own(guilds, user_id):
                raise GuildError("すでにギルドに所属しています。")
            target = next(
                (g for g in guilds.values() if g.passphrase_hash == digest), None
            )
            if action == "create":
                if target:
                    raise GuildError(
                        "そのあいことばは使用済みです。別のあいことばを入力してください。"
                    )
                target = GameGuild(str(uuid4()), name, digest, user_id, (member,))
            elif target is None:
                raise GuildError("あいことばに一致するギルドがありません。")
            elif len(target.members) >= MAX_MEMBERS:
                raise GuildError("このギルドは満員です（最大6人）。")
            return GuildConfirmation(
                action,
                user_id,
                server.id,
                member.server_joined_at,
                target,
                time.monotonic() + CONFIRM_SECONDS,
            )

    @staticmethod
    def apply_confirmation(guilds, confirmation, member):
        target = confirmation.target
        own = GuildService.own(guilds, member.user_id)
        if own:
            if own.id == target.id:
                return own  # 保存成功・応答失敗後の再試行。
            raise GuildError("すでに別のギルドに所属しています。")
        if confirmation.action == "create":
            if any(
                g.passphrase_hash == target.passphrase_hash for g in guilds.values()
            ):
                raise GuildError(
                    "そのあいことばは使用済みです。作成画面を開き直してください。"
                )
            guilds[target.id] = replace(target, members=(member,))
        else:
            current = guilds.get(target.id)
            if current is None or (
                current.name,
                current.leader_id,
                current.passphrase_hash,
            ) != (target.name, target.leader_id, target.passphrase_hash):
                raise GuildError(
                    "ギルド情報が変わりました。あいことばを入力し直して確認してください。"
                )
            if len(current.members) >= MAX_MEMBERS:
                raise GuildError("このギルドは満員です（最大6人）。")
            guilds[current.id] = replace(current, members=(*current.members, member))
        return guilds[target.id]

    @staticmethod
    async def confirm(server, user_id, confirmation):
        if (
            server is None
            or server.id != confirmation.server_id
            or user_id != confirmation.owner_id
        ):
            raise GuildError("この確認画面は開いた本人だけが操作できます。")
        if time.monotonic() >= confirmation.expires_at:
            raise GuildError(
                "確認の有効期限が切れました。トップ画面からやり直してください。"
            )
        # 脱退・再参加とリーダー退出を、確定直前にも検出する。
        await GuildService.reconcile(server, user_id)
        if confirmation.action == "join":
            await GuildService.reconcile(server, confirmation.target.leader_id)
        member = await GuildService.current_member(server, user_id)
        if member is None or member.server_joined_at != confirmation.server_joined_at:
            raise GuildError(
                "サーバーの所属が変わりました。トップ画面からやり直してください。"
            )
        async with GuildService.transaction(server.id) as guilds:
            if time.monotonic() >= confirmation.expires_at:
                raise GuildError(
                    "確認の有効期限が切れました。トップ画面からやり直してください。"
                )
            return GuildService.apply_confirmation(guilds, confirmation, member)
