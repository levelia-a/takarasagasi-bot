"""同一VC内のパーティー作成・参加・退出と、音声状態の照合。"""

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
                current[party.id] = replace(party, members=members, leader_id=leader)
        return current

    @staticmethod
    def apply_action(parties, voices, user_id, action, party_id):
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
            if own and own.id != party_id:
                raise PartyError(
                    "すでにパーティーに所属しています。先に脱退してください。"
                )
            if own is None:
                parties[party_id] = replace(target, members=(*target.members, user_id))
        elif action in ("leave", "disband"):
            # 古い画面で新しい所属を削除しないよう、表示したパーティーIDに束縛する。
            if own is None or own.id != party_id:
                raise PartyError("所属が変わっています。現在の状態に更新しました。")
            if action == "disband":
                if own.leader_id != user_id:
                    raise PartyError("解散できるのは現在のリーダーだけです。")
                del parties[own.id]
            else:
                members = tuple(uid for uid in own.members if uid != user_id)
                if members:
                    leader = own.leader_id if own.leader_id in members else members[0]
                    parties[own.id] = replace(own, members=members, leader_id=leader)
                else:
                    del parties[own.id]
        elif action != "refresh":
            raise ValueError("Unknown party action")

    @staticmethod
    async def run(guild, user_id=None, action="refresh", party_id=None):
        """照合・認可・更新を同一トランザクションで行い、最新画面を返す。"""
        PartyService.voice_members(guild)
        error = None
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
                        )
                        for row in rows
                    }
                    # DBロック待ちの間にVCが変わる可能性があるため、取得後に読む。
                    voices = PartyService.voice_members(guild)
                    parties = PartyService.reconcile(before, voices)
                    try:
                        PartyService.apply_action(
                            parties, voices, user_id, action, party_id
                        )
                    except PartyError as caught:
                        error = caught
                    await PartyRepository.save_party_changes(
                        cursor, guild.id, before, parties
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        if error:
            raise error
        channel_id = voices.get(user_id)
        return PartyScreen(
            channel_id,
            tuple(p for p in parties.values() if p.channel_id == channel_id),
            next((p for p in parties.values() if user_id in p.members), None),
        )
