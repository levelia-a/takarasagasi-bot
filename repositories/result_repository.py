class ResultRepository:
    def __init__(self, database):
        self.database = database

    async def save(self, session):
        async with self.database.transaction() as cursor:
            await cursor.execute(
                "INSERT INTO statistics "
                "(session_id, user_id, user_name, difficulty, start_price, success_count, "
                "final_reward, result, failure_point, is_test) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE session_id = session_id",
                (
                    session.id,
                    session.user_id,
                    session.user_name,
                    session.difficulty_name,
                    session.price,
                    session.success_count,
                    session.reward,
                    session.result,
                    session.exploration_count if session.result == "failure" else None,
                    session.is_test,
                ),
            )

    async def summary(self):
        async with self.database.transaction() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(start_price), 0) AS consumed, "
                "COALESCE(SUM(final_reward), 0) AS payout, COALESCE(MAX(final_reward), 0) AS max_payout "
                "FROM statistics WHERE is_test = 0"
            )
            summary = await cursor.fetchone()
            await cursor.execute(
                "SELECT difficulty, COUNT(*) AS count FROM statistics WHERE is_test = 0 GROUP BY difficulty"
            )
            summary["difficulties"] = {
                row["difficulty"]: row["count"] for row in await cursor.fetchall()
            }
            return summary

    async def recent(self):
        async with self.database.transaction() as cursor:
            await cursor.execute("SELECT * FROM statistics ORDER BY id DESC LIMIT 10")
            return await cursor.fetchall()

    async def delete_test_with_log(self, admin_id, admin_name):
        async with self.database.transaction() as cursor:
            await cursor.execute("DELETE FROM statistics WHERE is_test = 1")
            deleted = cursor.rowcount
            await cursor.execute(
                "INSERT INTO admin_logs (admin_id, admin_name, action, detail) VALUES (%s, %s, %s, %s)",
                (admin_id, admin_name, "テストデータ削除", f"{deleted}件削除"),
            )
            return deleted
