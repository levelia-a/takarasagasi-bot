"""難易度解放システム。

初級は最初から解放し、初級の探索回数で中級、中級の探索回数で上級を解放する。
解放に必要な回数は管理者設定から変更できる。
"""

from repositories.progress_repository import ProgressRepository
from services.db_service import DbService


class DifficultyLocked(ValueError):
    pass


class ProgressService:
    @staticmethod
    async def get(user_id):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            row = await ProgressRepository.get_progress_by_user_id(cursor, user_id)
        return row or {
            "beginner_explorations": 0,
            "intermediate_explorations": 0,
            "intermediate_unlocked": 0,
            "advanced_unlocked": 0,
        }

    @staticmethod
    async def require_unlocked(user_id, difficulty, settings):
        """開始前に難易度の解放状態を確認し、未解放なら残り回数を通知する。"""
        if difficulty == "beginner":
            return
        progress = await ProgressService.get(user_id)
        if difficulty == "intermediate" and progress["intermediate_unlocked"]:
            return
        if difficulty == "advanced" and progress["advanced_unlocked"]:
            return
        if difficulty == "intermediate":
            current, required = progress["beginner_explorations"], settings["intermediate_unlock"]
            if current < required:
                raise DifficultyLocked(
                    f"🔒 中級宝探しはまだ解放されていません。\n"
                    f"初級探索：**{current}/{required}回**\nあと **{required-current}回** です。"
                )
        elif difficulty == "advanced":
            current, required = progress["intermediate_explorations"], settings["advanced_unlock"]
            if current < required:
                raise DifficultyLocked(
                    f"🔒 上級宝探しはまだ解放されていません。\n"
                    f"中級探索：**{current}/{required}回**\nあと **{required-current}回** です。"
                )

    @staticmethod
    async def record_exploration(user_id, difficulty, settings):
        """通常プレイの探索を1回記録し、今回解放された難易度があれば返す。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            progress = await ProgressRepository.increment_explorations(
                cursor, user_id, difficulty
            )
        if (
            difficulty == "beginner"
            and not progress["intermediate_unlocked"]
            and progress["beginner_explorations"] >= settings["intermediate_unlock"]
        ):
            async with (
                DbService.get_connection() as connection,
                connection.cursor() as cursor,
            ):
                await ProgressRepository.mark_unlocked(cursor, user_id, "intermediate")
            return "intermediate"
        if (
            difficulty == "intermediate"
            and not progress["advanced_unlocked"]
            and progress["intermediate_explorations"] >= settings["advanced_unlock"]
        ):
            async with (
                DbService.get_connection() as connection,
                connection.cursor() as cursor,
            ):
                await ProgressRepository.mark_unlocked(cursor, user_id, "advanced")
            return "advanced"
        return None
