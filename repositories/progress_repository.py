"""難易度解放システム用のユーザー探索回数をMySQLへ保存・取得する。"""


class ProgressRepository:
    @staticmethod
    async def get_progress_by_user_id(cursor, user_id):
        """ユーザーの難易度解放用探索回数を取得する。"""
        await cursor.execute(
            """SELECT beginner_explorations, intermediate_explorations
               FROM user_progress WHERE user_id = %s""",
            (user_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    async def increment_explorations(cursor, user_id, difficulty, exploration_id):
        """同じ探索IDを二重加算せず、指定難易度の探索回数を1増やす。"""
        column = {
            "beginner": "beginner_explorations",
            "intermediate": "intermediate_explorations",
        }.get(difficulty)
        if column is None:
            return await ProgressRepository.get_progress_by_user_id(cursor, user_id)

        await cursor.execute(
            """INSERT IGNORE INTO user_progress_events (exploration_id, user_id)
               VALUES (%s, %s)""",
            (exploration_id, user_id),
        )
        if cursor.rowcount:
            await cursor.execute(
                f"""INSERT INTO user_progress (user_id, {column}) VALUES (%s, 1)
                    ON DUPLICATE KEY UPDATE {column} = {column} + 1""",
                (user_id,),
            )
        return await ProgressRepository.get_progress_by_user_id(cursor, user_id)
