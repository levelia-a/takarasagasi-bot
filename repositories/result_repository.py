class ResultRepository:
    async def save(self, cursor, result):
        await cursor.execute(
            "INSERT INTO statistics "
            "(session_id, user_id, user_name, difficulty, start_price, success_count, "
            "final_reward, result, failure_point, is_test) "
            "VALUES (%(session_id)s, %(user_id)s, %(user_name)s, %(difficulty)s, "
            "%(start_price)s, %(success_count)s, %(final_reward)s, %(result)s, "
            "%(failure_point)s, %(is_test)s) "
            "ON DUPLICATE KEY UPDATE session_id = session_id",
            result,
        )

    async def summary(self, cursor):
        await cursor.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(start_price), 0) AS consumed, "
            "COALESCE(SUM(final_reward), 0) AS payout, COALESCE(MAX(final_reward), 0) AS max_payout "
            "FROM statistics WHERE is_test = 0"
        )
        return await cursor.fetchone()

    async def counts_by_difficulty(self, cursor):
        await cursor.execute(
            "SELECT difficulty, COUNT(*) AS count FROM statistics WHERE is_test = 0 GROUP BY difficulty"
        )
        return await cursor.fetchall()

    async def recent(self, cursor):
        await cursor.execute("SELECT * FROM statistics ORDER BY id DESC LIMIT 10")
        return await cursor.fetchall()

    async def delete_test(self, cursor):
        await cursor.execute("DELETE FROM statistics WHERE is_test = 1")
        return cursor.rowcount
