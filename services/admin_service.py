class AdminService:
    def __init__(self, db, results, logs):
        self.db = db
        self.results = results
        self.logs = logs

    async def statistics(self):
        # 合計と難易度別の件数を同じスナップショットから取得する。
        async with self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    summary = await self.results.summary(cursor)
                    rows = await self.results.counts_by_difficulty(cursor)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        summary["difficulties"] = {row["difficulty"]: row["count"] for row in rows}
        return summary

    async def history(self):
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await self.results.recent(cursor)

    async def admin_logs(self):
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await self.logs.recent(cursor)

    async def delete_test(self, admin_id, admin_name):
        async with self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    deleted = await self.results.delete_test(cursor)
                    await self.logs.insert(
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
