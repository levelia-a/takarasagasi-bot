"""難易度解放システム用のユーザー探索回数・通知状態をMySQLへ保存する。"""


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
        """同じ探索IDを二重加算せず、探索回数と今回の新規加算有無を返す。"""
        column = {
            "beginner": "beginner_explorations",
            "intermediate": "intermediate_explorations",
        }.get(difficulty)
        if column is None:
            return await ProgressRepository.get_progress_by_user_id(cursor, user_id), False

        await cursor.execute(
            """INSERT IGNORE INTO user_progress_events (exploration_id, user_id)
               VALUES (%s, %s)""",
            (exploration_id, user_id),
        )
        counted = bool(cursor.rowcount)
        if counted:
            await cursor.execute(
                f"""INSERT INTO user_progress (user_id, {column}) VALUES (%s, 1)
                    ON DUPLICATE KEY UPDATE {column} = {column} + 1""",
                (user_id,),
            )
        return await ProgressRepository.get_progress_by_user_id(cursor, user_id), counted

    @staticmethod
    async def has_unlock_notification(cursor, user_id, difficulty):
        """Discordへ表示済みの解放通知か確認する。"""
        await cursor.execute(
            """SELECT 1 FROM unlock_notifications
               WHERE user_id = %s AND difficulty = %s""",
            (user_id, difficulty),
        )
        return await cursor.fetchone() is not None

    @staticmethod
    async def mark_unlock_notification(cursor, user_id, difficulty):
        """Discordへの表示成功後に通知済みとして記録する。"""
        await cursor.execute(
            """INSERT IGNORE INTO unlock_notifications (user_id, difficulty)
               VALUES (%s, %s)""",
            (user_id, difficulty),
        )
