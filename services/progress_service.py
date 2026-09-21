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
        return row or {"beginner_explorations": 0, "intermediate_explorations": 0}

    @staticmethod
    async def require_unlocked(user_id, difficulty, settings):
        if difficulty == "beginner":
            return
        progress = await ProgressService.get(user_id)
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
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            progress = await ProgressRepository.increment_explorations(
                cursor, user_id, difficulty
            )
        if difficulty == "beginner" and progress["beginner_explorations"] == settings["intermediate_unlock"]:
            return "intermediate"
        if difficulty == "intermediate" and progress["intermediate_explorations"] == settings["advanced_unlock"]:
            return "advanced"
        return None
