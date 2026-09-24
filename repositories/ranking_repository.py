"""通常プレイの確定結果からランキングをまとめて取得する。"""


class RankingRepository:
    @staticmethod
    async def get_top_10_rankings(cursor):
        await cursor.execute("""
            WITH totals AS (
                SELECT user_id, SUM(success_count) AS successes,
                       SUM(final_reward) AS payout, MAX(final_reward) AS best
                FROM statistics WHERE is_test = 0 GROUP BY user_id
            ), metrics AS (
                SELECT user_id, 'successes' AS metric, successes AS value FROM totals
                UNION ALL
                SELECT user_id, 'payout', payout FROM totals
                UNION ALL
                SELECT user_id, 'best', best FROM totals
            ), ranked AS (
                SELECT user_id, metric, value,
                       RANK() OVER (PARTITION BY metric ORDER BY value DESC) AS position,
                       ROW_NUMBER() OVER (
                           PARTITION BY metric ORDER BY value DESC, user_id
                       ) AS row_number_in_metric
                FROM metrics WHERE value > 0
            )
            SELECT user_id, metric, value, position FROM ranked
            WHERE row_number_in_metric <= 10
            ORDER BY metric, row_number_in_metric
        """)
        return await cursor.fetchall()
