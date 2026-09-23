class ResultRepository:
    @staticmethod
    async def get_statistics_page_before_id(cursor, before_id=None):
        """次ページ判定用の1件を含め、新しい順に最大11件取得する。"""
        if before_id is None:
            await cursor.execute("SELECT * FROM statistics ORDER BY id DESC LIMIT 11")
        else:
            await cursor.execute(
                "SELECT * FROM statistics WHERE id < %s ORDER BY id DESC LIMIT 11",
                (before_id,),
            )
        return await cursor.fetchall()

    @staticmethod
    async def insert_statistics_record_if_session_id_not_exists(cursor, result):
        """未登録のセッションIDのゲーム結果をstatisticsに追加する。"""
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

    @staticmethod
    async def get_non_test_statistics_summary(cursor):
        """テスト結果を除くプレイ数・消費額・報酬額を集計する。"""
        await cursor.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(start_price), 0) AS consumed, "
            "COALESCE(SUM(final_reward), 0) AS payout, COALESCE(MAX(final_reward), 0) AS max_payout "
            "FROM statistics WHERE is_test = 0"
        )
        return await cursor.fetchone()

    @staticmethod
    async def get_non_test_statistics_counts_grouped_by_difficulty(cursor):
        """テスト結果を除くプレイ数を難易度ごとに取得する。"""
        await cursor.execute(
            "SELECT difficulty, COUNT(*) AS count FROM statistics WHERE is_test = 0 GROUP BY difficulty"
        )
        return await cursor.fetchall()

    @staticmethod
    async def get_latest_10_statistics(cursor):
        """statisticsからIDの降順で最新10件を取得する。"""
        await cursor.execute("SELECT * FROM statistics ORDER BY id DESC LIMIT 10")
        return await cursor.fetchall()

    @staticmethod
    async def delete_test_statistics(cursor):
        """statisticsのテスト結果を削除し、削除件数を返す。"""
        await cursor.execute("DELETE FROM statistics WHERE is_test = 1")
        return cursor.rowcount
