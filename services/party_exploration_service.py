"""リーダー操作の共有探索。抽選は一度、全員の進捗・結果は一括で保存する。"""

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import ClassVar
from uuid import uuid4

from consts.treasure import DIFFICULTIES
from repositories.active_exploration_repository import (
    ActiveExplorationRepository,
    TreasureSessionExpired,
)
from repositories.progress_repository import ProgressRepository
from repositories.result_repository import ResultRepository
from repositories.settings_repository import SettingsRepository
from services.balance_service import BalanceService
from services.party_service import PartyError, PartyService
from services.settings_service import SettingsService
from services.treasure_catalog_service import TreasureCatalogService
from services.treasure_service import Exploration, TreasureService


@dataclass(frozen=True)
class Participant:
    user_id: int
    user_name: str
    session_id: str


@dataclass
class PartyRun:
    party_id: str
    guild_id: int
    channel_id: int
    leader_id: int
    participants: tuple[Participant, ...]
    session: Exploration
    version: int = 0
    pending: bool = False
    complete: bool = False
    aborted: str = ""
    expires: float = field(default_factory=lambda: time.monotonic() + 300)
    message_url: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def id(self):
        return self.session.id

    @property
    def user_ids(self):
        return tuple(p.user_id for p in self.participants)


class PartyExplorationService:
    runs: ClassVar[dict[str, PartyRun]] = {}

    @staticmethod
    async def create(guild, user_id, party_id, confirmation_id, difficulty):
        if difficulty not in DIFFICULTIES:
            raise PartyError("不明な難易度です。")
        async with PartyService.transaction(guild) as (cursor, parties, _):
            party = parties.get(party_id)
            if party is None or party.leader_id != user_id:
                raise PartyError("現在のリーダーだけが探索を開始できます。")
            if party.run_id:
                raise PartyError(
                    "共有探索は開始済みです。パーティー画面から確認してください。"
                )
            if (
                not confirmation_id
                or party.confirmation_id != confirmation_id
                or len(party.members) < 2
            ):
                raise PartyError(
                    "パーティーが変更されています。メンバーを確認して再度確定してください。"
                )
            settings = SettingsService.build_settings(
                await SettingsRepository.get_all_settings(cursor)
            )
            catalog = TreasureCatalogService.load_catalog()
            SettingsService.validate_settings(settings, catalog=catalog)
            if not settings["operation"]:
                raise PartyError("現在、宝探しは停止中です。")
            pool = TreasureCatalogService.require_available(
                BalanceService.apply_catalog(catalog, settings), difficulty
            )
            participants = []
            for uid in sorted(party.members):
                member = guild.get_member(uid)
                name = member.display_name if member else str(uid)
                progress = (
                    await ProgressRepository.get_progress_by_user_id(cursor, uid) or {}
                )
                key = {
                    "intermediate": "beginner_explorations",
                    "advanced": "intermediate_explorations",
                }.get(difficulty)
                if key and progress.get(key, 0) < settings[f"{difficulty}_unlock"]:
                    raise PartyError(
                        f"<@{uid}> はこの難易度をまだ解放していません。全員が解放済みの難易度を選んでください。"
                    )
                sid = str(uuid4())
                if not await ActiveExplorationRepository.claim(cursor, uid, sid):
                    raise PartyError(
                        f"<@{uid}> に進行中の探索があります。終了してから開始してください。"
                    )
                participants.append(Participant(uid, name, sid))
            session = TreasureService.build_session(
                user_id,
                str(guild.get_member(user_id)),
                difficulty,
                settings,
                pool,
                vc_members=len(participants),
                session_id=str(uuid4()),
            )
            run = PartyRun(
                party.id,
                guild.id,
                party.channel_id,
                user_id,
                tuple(participants),
                session,
            )
            # 外部I/Oを挟んだ後の現在のVCも確認する。
            voices = PartyService.voice_members(guild)
            if any(voices.get(uid) != party.channel_id for uid in party.members):
                raise PartyError("VCのメンバーが変わりました。再度確定してください。")
            parties[party.id] = replace(party, run_id=run.id)
        PartyExplorationService.runs[run.id] = run
        return run

    @staticmethod
    async def results_saved(cursor, run):
        if run.session.result is None:
            return False
        ids = tuple(p.session_id for p in run.participants)
        await cursor.execute(
            "SELECT session_id FROM statistics WHERE session_id IN ("
            + ",".join(["%s"] * len(ids))
            + ")",
            ids,
        )
        return len(await cursor.fetchall()) == len(ids)

    @staticmethod
    async def release(cursor, parties, run):
        for participant in run.participants:
            await ActiveExplorationRepository.release(
                cursor, participant.user_id, participant.session_id
            )
        party = parties.get(run.party_id)
        if party and party.run_id == run.id:
            parties[party.id] = replace(party, confirmation_id="", run_id="")

    @staticmethod
    async def step(guild, run, user_id, deeper, expected_version):
        async with run.lock:
            if user_id != run.leader_id:
                raise PartyError("探索を進められるのはリーダーだけです。")
            if run.aborted:
                raise PartyError(run.aborted)
            if run.complete:
                return run
            if expected_version != run.version:
                raise PartyError(
                    "この選択は処理済みです。最新の探索画面を確認してください。"
                )
            try:
                async with PartyService.transaction(guild) as (cursor, parties, voices):
                    # COMMIT成功後の通信断は確定済み結果で判別し、二重精算しない。
                    already_saved = await PartyExplorationService.results_saved(
                        cursor, run
                    )
                    if not already_saved:
                        party = parties.get(run.party_id)
                        if (
                            party is None
                            or party.run_id != run.id
                            or party.leader_id != run.leader_id
                            or set(party.members) != set(run.user_ids)
                            or any(
                                voices.get(uid) != run.channel_id
                                for uid in run.user_ids
                            )
                        ):
                            raise TreasureSessionExpired()
                        for participant in run.participants:
                            await ActiveExplorationRepository.refresh(
                                cursor, participant.user_id, participant.session_id
                            )
                        if not run.pending:
                            if deeper or run.session.exploration_count == 0:
                                TreasureService.roll(run.session)
                            else:
                                run.session.result = "retreat"
                            run.pending = True
                        for participant in run.participants:
                            if not run.session.is_test:
                                await ProgressRepository.increment_explorations(
                                    cursor,
                                    participant.user_id,
                                    run.session.difficulty,
                                    f"{participant.session_id}:{run.session.exploration_count}",
                                )
                            if run.session.result:
                                result = TreasureService.build_result(run.session) | {
                                    "session_id": participant.session_id,
                                    "user_id": participant.user_id,
                                    "user_name": participant.user_name,
                                }
                                await ResultRepository.insert_statistics_record_if_session_id_not_exists(
                                    cursor, result
                                )
                        if run.session.result:
                            await PartyExplorationService.release(cursor, parties, run)
                        else:
                            await cursor.execute(
                                "UPDATE party_states SET expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE) WHERE party_id = %s AND run_id = %s",
                                (run.party_id, run.id),
                            )
            except TreasureSessionExpired:
                await PartyExplorationService._abort(
                    guild,
                    run,
                    "メンバーの変更または操作期限切れにより共有探索を終了しました。宝物は確定していません。",
                )
                raise PartyError(run.aborted or "この探索は終了しました。") from None
            run.pending = False
            run.version += 1
            run.complete = run.session.result is not None
            run.expires = time.monotonic() + 300
            return run

    @staticmethod
    async def _abort(guild, run, reason):
        if run.complete or run.aborted:
            return
        async with PartyService.transaction(guild) as (cursor, parties, _):
            saved = await PartyExplorationService.results_saved(cursor, run)
            await PartyExplorationService.release(cursor, parties, run)
        run.complete = saved
        run.aborted = "" if saved else reason
        run.pending = False
        run.expires = time.monotonic() + 300

    @staticmethod
    async def abort(guild, run, reason, expected_version=None):
        async with run.lock:
            if expected_version is not None and expected_version != run.version:
                return False
            await PartyExplorationService._abort(guild, run, reason)
            return True

    @staticmethod
    async def expire_invalid(guild):
        voices = PartyService.voice_members(guild)
        changed = []
        for run in list(PartyExplorationService.runs.values()):
            if run.guild_id != guild.id:
                continue
            if run.complete or run.aborted:
                if time.monotonic() >= run.expires:
                    PartyExplorationService.runs.pop(run.id, None)
                continue
            screen = await PartyService.run(guild, run.leader_id)
            invalid = screen.own is None or screen.own.run_id != run.id
            if (
                invalid
                or time.monotonic() >= run.expires
                or any(voices.get(uid) != run.channel_id for uid in run.user_ids)
            ):
                ended = await PartyExplorationService.abort(
                    guild,
                    run,
                    "VCの退出・移動または操作期限切れにより共有探索を終了しました。宝物は確定していません。",
                    expected_version=run.version,
                )
                if ended:
                    changed.append(run)
        return changed
