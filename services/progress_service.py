"""難易度解放システム。

初級は最初から挑戦できる。
中級は初級の探索回数、上級は中級の探索回数を現在の管理者設定と比較して判定する。
解放状態そのものは保存せず、常に探索回数を基準にする。
"""

from repositories.progress_repository import ProgressRepository
from services.db_service import DbService


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

    @staticmethod
    async def record_exploration(user_id, difficulty, settings):
        """通常プレイの探索を1回記録し、今回ちょうど到達した難易度があれば返す。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            progress = await ProgressRepository.increment_explorations(
                cursor, user_id, difficulty
            )

        if (
            difficulty == "beginner"
            and progress["beginner_explorations"] == settings["intermediate_unlock"]
        ):
            return "intermediate"
        if (
            difficulty == "intermediate"
            and progress["intermediate_explorations"] == settings["advanced_unlock"]
        ):
            return "advanced"
        return None
