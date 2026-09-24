"""定期集計したランキングを、完成したスナップショット単位で公開する。"""

from dataclasses import dataclass
import json
from datetime import datetime, timezone

from repositories.ranking_repository import RankingRepository
from repositories.settings_repository import SettingsRepository
from services.db_service import DbService


@dataclass(frozen=True)
class RankingEntry:
    user_id: int
    metric: str
    value: int
    position: int


@dataclass(frozen=True)
class RankingSnapshot:
    entries: tuple[RankingEntry, ...]
    updated_at: datetime


class RankingService:
    _snapshot: RankingSnapshot | None = None

    @staticmethod
    async def refresh():
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            rows = await RankingRepository.get_top_10_rankings(cursor)
        snapshot = RankingSnapshot(
            tuple(RankingEntry(
                int(row['user_id']), row['metric'], int(row['value']),
                int(row['position']),
            ) for row in rows),
            datetime.now(timezone.utc),
        )
        # 取得失敗時は前回の結果と更新日時を維持する。
        RankingService._snapshot = snapshot
        return snapshot

    @staticmethod
    def get_snapshot():
        return RankingService._snapshot

    @staticmethod
    async def get_panel():
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            rows = await SettingsRepository.get_all_settings(cursor)
        value = next((row['value'] for row in rows if row['key'] == 'ranking_panel'), None)
        return json.loads(value) if value else None

    @staticmethod
    async def save_panel(guild_id, channel_id, message_id):
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            await SettingsRepository.upsert_setting_by_key(
                cursor, 'ranking_panel', json.dumps([guild_id, channel_id, message_id]),
            )
