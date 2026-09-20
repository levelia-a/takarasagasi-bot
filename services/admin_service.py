class AdminService:
    def __init__(self, db, results, logs):
        """管理操作で使用するDBとレポジトリを保持する。"""
        self.db = db
        self.results = results
        self.logs = logs

    async def statistics(self):
        # 合計と難易度別の件数を同じスナップショットから取得する。
        """テスト結果を除いた全体集計と難易度別件数を返す。"""
        async with self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    summary = await self.results.get_non_test_statistics_summary(cursor)
                    rows = await self.results.get_non_test_statistics_counts_grouped_by_difficulty(
                        cursor
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        summary["difficulties"] = {row["difficulty"]: row["count"] for row in rows}
        return summary

    async def history(self):
        """最新10件の宝探し履歴を取得する。"""
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await self.results.get_latest_10_statistics(cursor)

    async def admin_logs(self):
        """最新10件の管理者操作ログを取得する。"""
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await self.logs.get_latest_10_admin_logs(cursor)

    async def delete_test(self, admin_id, admin_name):
        """テスト履歴の削除と管理ログ保存をまとめて確定する。"""
        async with self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    deleted = await self.results.delete_test_statistics(cursor)
                    await self.logs.insert_admin_log(
                        cursor,
                        admin_id,
                        admin_name,
                        "テストデータ削除",
                        f"{deleted}件削除",
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        return deleted
