"""難易度解放システム。

初級は最初から挑戦できる。
中級は初級の探索回数、上級は中級の探索回数を現在の管理者設定と比較して判定する。
解放状態そのものは保存せず、常に探索回数を基準にする。
"""

from repositories.progress_repository import ProgressRepository
from repositories.result_repository import ResultRepository
from services.db_service import DbService
from services.settings_service import SettingsService


class DifficultyLocked(ValueError):
    pass


class ProgressService:
    @staticmethod
    async def get_exploration_counts(user_id):
        """ユーザーの探索回数を取得する。未記録なら0回として扱う。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            row = await ProgressRepository.get_progress_by_user_id(cursor, user_id)
        return row or {
            "beginner_explorations": 0,
            "intermediate_explorations": 0,
        }

    @staticmethod
    async def require_unlocked(user_id, difficulty, settings):
        """現在の探索回数と解放条件を比較し、未達なら開始を拒否する。"""
        if difficulty == "beginner":
            return

        progress = await ProgressService.get_exploration_counts(user_id)
        if difficulty == "intermediate":
            current = progress["beginner_explorations"]
            required = settings["intermediate_unlock"]
            if current < required:
                raise DifficultyLocked(
                    f"🔒 中級宝探しはまだ解放されていません。\n"
                    f"初級探索：**{current}/{required}回**\nあと **{required-current}回** です。"
                )
        elif difficulty == "advanced":
            current = progress["intermediate_explorations"]
            required = settings["advanced_unlock"]
            if current < required:
                raise DifficultyLocked(
                    f"🔒 上級宝探しはまだ解放されていません。\n"
                    f"中級探索：**{current}/{required}回**\nあと **{required-current}回** です。"
                )

        # 条件引き下げで既に到達済みでも、未表示なら次の挑戦画面で通知する。
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            if not await ProgressRepository.has_unlock_notification(
                cursor, user_id, difficulty
            ):
                return difficulty
        return None

    @staticmethod
    async def record_exploration(user_id, difficulty, exploration_id, result=None):
        """探索進捗を保存し、終了結果があれば同じトランザクションで保存する。"""
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    progress, _ = await ProgressRepository.increment_explorations(
                        cursor, user_id, difficulty, exploration_id
                    )
                    if result is not None:
                        await ResultRepository.insert_statistics_record_if_session_id_not_exists(
                            cursor, result
                        )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

        # ゲーム開始後に管理者が条件を変更していても、通知は現在設定で判定する。
        settings = await SettingsService.get_all()
        unlocked = None
        if (
            difficulty == "beginner"
            and progress["beginner_explorations"] >= settings["intermediate_unlock"]
        ):
            target = "intermediate"
        elif (
            difficulty == "intermediate"
            and progress["intermediate_explorations"] >= settings["advanced_unlock"]
        ):
            target = "advanced"
        else:
            target = None

        if target is not None:
            async with DbService.get_connection() as connection, connection.cursor() as cursor:
                if not await ProgressRepository.has_unlock_notification(
                    cursor, user_id, target
                ):
                    unlocked = target

        # user_progress_events は冪等性キーなので正常完了後も保持する。
        # DB応答を失った再試行でも同じ exploration_id を二重加算しないため削除しない。
        return unlocked

    @staticmethod
    async def mark_unlock_notification(user_id, difficulty):
        """Discordへの通知表示が成功した後だけ通知済み状態を保存する。"""
        if difficulty is None:
            return
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            await ProgressRepository.mark_unlock_notification(
                cursor, user_id, difficulty
            )

