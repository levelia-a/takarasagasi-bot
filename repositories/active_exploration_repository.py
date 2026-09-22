"""同一ユーザーの宝探し同時進行をDBで防止する。"""

from pymysql.err import IntegrityError


class ActiveExplorationRepository:
    @staticmethod
    async def claim(cursor, user_id, session_id):
        """未使用または期限切れのユーザー枠を取得する。"""
        await cursor.execute(
            "DELETE FROM active_explorations WHERE user_id = %s AND expires_at <= NOW()",
            (user_id,),
        )
        try:
            await cursor.execute(
                """INSERT INTO active_explorations (user_id, session_id, expires_at)
                   VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE))""",
                (user_id, session_id),
            )
        except IntegrityError:
            return False
        return True

    @staticmethod
    async def refresh(cursor, user_id, session_id):
        """操作中のセッション期限を5分先へ延長する。"""
        await cursor.execute(
            """UPDATE active_explorations
               SET expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE)
               WHERE user_id = %s AND session_id = %s""",
            (user_id, session_id),
        )

    @staticmethod
    async def release(cursor, user_id, session_id):
        """指定セッションが所有するユーザー枠だけを解放する。"""
        await cursor.execute(
            "DELETE FROM active_explorations WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
