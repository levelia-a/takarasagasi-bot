"""同一ユーザーの宝探し同時進行をDBで防止する。"""

from pymysql.err import IntegrityError


class TreasureSessionExpired(ValueError):
    def __init__(self):
        super().__init__("操作期限が切れました。宝探しパネルから開始し直してください。")


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
        except IntegrityError as error:
            if error.args[0] != 1062:
                raise
            return False
        return True

    @staticmethod
    async def refresh(cursor, user_id, session_id):
        """有効な所有者だけ期限を延長する。transaction内なら行ロックも保持する。"""
        await cursor.execute(
            """UPDATE active_explorations
               SET expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE)
               WHERE user_id = %s AND session_id = %s AND expires_at > NOW()""",
            (user_id, session_id),
        )
        if cursor.rowcount:
            return
        # DATETIMEは秒単位。同じ秒の更新は変更行数0でも所有権が有効な場合がある。
        await cursor.execute(
            """SELECT 1 FROM active_explorations
               WHERE user_id = %s AND session_id = %s AND expires_at > NOW()
               FOR UPDATE""",
            (user_id, session_id),
        )
        if await cursor.fetchone() is None:
            raise TreasureSessionExpired()

    @staticmethod
    async def release(cursor, user_id, session_id):
        """指定セッションが所有するユーザー枠だけを解放する。"""
        await cursor.execute(
            "DELETE FROM active_explorations WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
