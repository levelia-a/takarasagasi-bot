"""難易度解放システム用のユーザー探索進捗をMySQLへ保存・取得する。"""

class ProgressRepository:
    @staticmethod
    async def get_progress_by_user_id(cursor, user_id):
        """ユーザーの難易度解放用探索回数を取得する。"""
        await cursor.execute(
            """SELECT beginner_explorations, intermediate_explorations,
                      intermediate_unlocked, advanced_unlocked
               FROM user_progress WHERE user_id = %s""",
            (user_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    async def increment_explorations(cursor, user_id, difficulty):
        """指定難易度の探索回数を1増やし、更新後の進捗を返す。"""
        column = {
            "beginner": "beginner_explorations",
            "intermediate": "intermediate_explorations",
        }.get(difficulty)
        if column is None:
            return await ProgressRepository.get_progress_by_user_id(cursor, user_id)

    @staticmethod
    async def mark_unlocked(cursor, user_id, difficulty):
        """一度獲得した難易度解放を永久に保存する。"""
        column = {
            "intermediate": "intermediate_unlocked",
            "advanced": "advanced_unlocked",
        }[difficulty]
        await cursor.execute(
            f"""INSERT INTO user_progress (user_id, {column}) VALUES (%s, TRUE)
                ON DUPLICATE KEY UPDATE {column} = TRUE""",
            (user_id,),
        )
        await cursor.execute(
            f"""INSERT INTO user_progress (user_id, {column}) VALUES (%s, 1)
                ON DUPLICATE KEY UPDATE {column} = {column} + 1""",
            (user_id,),
        )
        return await ProgressRepository.get_progress_by_user_id(cursor, user_id)
