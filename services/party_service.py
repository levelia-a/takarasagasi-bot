"""同一VC内のパーティー作成・参加・退出と、音声状態の照合。"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

from repositories.party_repository import PartyRepository
from services.db_service import DbService


class PartyError(ValueError):
    pass


@dataclass(frozen=True)
class Party:
    id: str
    channel_id: int
    leader_id: int
    members: tuple[int, ...]
    confirmation_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class PartyScreen:
    channel_id: int | None
    parties: tuple[Party, ...]
    own: Party | None


class PartyService:
    @staticmethod
    def voice_members(guild):
        """通常VCの現在のキャッシュを使う。ステージ・Botは対象外。"""
        if guild is None or guild.unavailable:
            raise PartyError(
                "サーバー情報を確認できません。少し待ってから更新してください。"
            )
        return {
            member.id: channel.id
            for channel in guild.voice_channels
            for member in channel.members
            if not member.bot
        }

    @staticmethod
    def reconcile(parties, voices):
        current = {}
        for party in parties.values():
            members = tuple(
                uid for uid in party.members if voices.get(uid) == party.channel_id
            )
            if members:
                leader = party.leader_id if party.leader_id in members else members[0]
                changed = members != party.members or leader != party.leader_id
                current[party.id] = replace(
                    party,
                    members=members,
                    leader_id=leader,
                    confirmation_id="" if changed else party.confirmation_id,
                    run_id="" if changed else party.run_id,
                )
        return current

    @staticmethod
    def apply_action(
        parties,
        voices,
        user_id,
        action,
        party_id,
        confirmation_id=None,
        expected_members=None,
        target_user_id=None,
    ):
        own = next((p for p in parties.values() if user_id in p.members), None)
        channel_id = voices.get(user_id)
        if action in ("create", "join") and channel_id is None:
            raise PartyError("パーティーを組むにはVCに参加してください。")
        if action == "create":
            # 二重クリックやDiscordへの応答失敗後の再試行でも一つだけ作る。
            if own is None:
                party = Party(str(uuid4()), channel_id, user_id, (user_id,))
                parties[party.id] = party
        elif action == "join":
            target = parties.get(party_id)
            if target is None:
                raise PartyError(
                    "このパーティーは解散済みです。募集一覧を更新しました。"
                )
            if target.channel_id != channel_id:
                raise PartyError("同じVCにいる人のパーティーにだけ参加できます。")
            if (target.confirmation_id or target.run_id) and own is None:
                raise PartyError(
                    "このパーティーは確定済みです。組み直すまで参加できません。"
                )
            if own and own.id != party_id:
                raise PartyError(
                    "すでにパーティーに所属しています。先に脱退してください。"
                )
            if own is None:
                parties[party_id] = replace(target, members=(*target.members, user_id))
        elif action in ("leave", "disband", "confirm", "reform", "transfer_leader"):
            # 古い画面で新しい所属を削除しないよう、表示したパーティーIDに束縛する。
            if own is None or own.id != party_id:
                raise PartyError("所属が変わっています。現在の状態に更新しました。")
            if action == "transfer_leader":
                if own.leader_id != user_id:
                    raise PartyError("リーダーを交代できるのは現在のリーダーだけです。")
                if own.run_id:
                    raise PartyError(
                        "共有探索中はリーダーを交代できません。探索の終了後に操作してください。"
                    )
                if confirmation_id != own.confirmation_id:
                    raise PartyError(
                        "確定状態が変わりました。リーダーの交代画面を開き直してください。"
                    )
                if target_user_id == user_id:
                    raise PartyError("交代先には自分以外のメンバーを選んでください。")
                if (
                    target_user_id not in own.members
                    or voices.get(target_user_id) != own.channel_id
                ):
                    raise PartyError(
                        "交代先は同じVCにいるパーティーメンバーから選んでください。"
                    )
                parties[own.id] = replace(
                    own,
                    leader_id=target_user_id,
                    # 確定済みの構成は維持し、以前の難易度画面だけを無効化する。
                    confirmation_id=str(uuid4()) if own.confirmation_id else "",
                )
            elif action in ("confirm", "reform"):
                if own.leader_id != user_id:
                    raise PartyError("確定・組み直しはリーダーだけが操作できます。")
                if own.run_id:
                    raise PartyError(
                        "共有探索中です。探索が終了してから組み直してください。"
                    )
                if action == "reform" and confirmation_id != own.confirmation_id:
                    raise PartyError(
                        "確定状態が変わっています。最新のパーティー画面を開いてください。"
                    )
                if action == "confirm" and len(own.members) < 2:
                    raise PartyError("パーティーの確定には2人以上必要です。")
                if (
                    action == "confirm"
                    and expected_members is not None
                    and set(own.members) != set(expected_members)
                ):
                    raise PartyError(
                        "メンバーが変わりました。最新の一覧を確認して確定してください。"
                    )
                parties[own.id] = replace(
                    own,
                    confirmation_id=(own.confirmation_id or str(uuid4()))
                    if action == "confirm"
                    else "",
                )
            elif action == "disband":
                if own.leader_id != user_id:
                    raise PartyError("解散できるのは現在のリーダーだけです。")
                del parties[own.id]
            else:
                members = tuple(uid for uid in own.members if uid != user_id)
                if members:
                    leader = own.leader_id if own.leader_id in members else members[0]
                    parties[own.id] = replace(
                        own,
                        members=members,
                        leader_id=leader,
                        confirmation_id="",
                        run_id="",
                    )
                else:
                    del parties[own.id]
        elif action != "refresh":
            raise ValueError("Unknown party action")

    @staticmethod
    @asynccontextmanager
    async def transaction(guild):
        """パーティーと関連データを同じサーバーロック内で更新する。"""
        PartyService.voice_members(guild)
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    await PartyRepository.get_guild_lock_for_update(cursor, guild.id)
                    rows, member_rows = await PartyRepository.get_parties_by_guild_id(
                        cursor, guild.id
                    )
                    members = {}
                    for row in member_rows:
                        members.setdefault(row["party_id"], []).append(row["user_id"])
                    before = {
                        row["id"]: Party(
                            row["id"],
                            row["channel_id"],
                            row["leader_id"],
                            tuple(members.get(row["id"], ())),
                            row.get("confirmation_id", ""),
                            row.get("run_id", ""),
                        )
                        for row in rows
                    }
                    # DBロック待ちの間にVCが変わる可能性があるため、取得後に読む。
                    voices = PartyService.voice_members(guild)
                    parties = PartyService.reconcile(before, voices)
                    yield cursor, parties, voices
                    await PartyRepository.save_party_changes(
                        cursor, guild.id, before, parties
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    @staticmethod
    async def run(
        guild,
        user_id=None,
        action="refresh",
        party_id=None,
        confirmation_id=None,
        expected_members=None,
        target_user_id=None,
    ):
        """照合・認可・更新を同一トランザクションで行い、最新画面を返す。"""
        error = None
        async with PartyService.transaction(guild) as (_, parties, voices):
            try:
                PartyService.apply_action(
                    parties,
                    voices,
                    user_id,
                    action,
                    party_id,
                    confirmation_id,
                    expected_members,
                    target_user_id,
                )
            except PartyError as caught:
                error = caught
        if error:
            raise error
        channel_id = voices.get(user_id)
        return PartyScreen(
            channel_id,
            tuple(
                p
                for p in parties.values()
                if p.channel_id == channel_id and not p.confirmation_id and not p.run_id
            ),
            next((p for p in parties.values() if user_id in p.members), None),
        )
