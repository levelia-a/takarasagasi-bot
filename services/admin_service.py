from repositories.admin_log_repository import AdminLogRepository
from repositories.result_repository import ResultRepository
from services.db_service import DbService


class AdminService:
    @staticmethod
    async def history_page(before_id=None, user_id=None):
        """履歴10件と、さらに古い履歴が存在するかを返す。"""
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            rows = await ResultRepository.get_statistics_page_before_id(cursor, before_id, user_id)
        return list(rows[:10]), len(rows) > 10

    @staticmethod
    async def statistics():
        # 合計と難易度別の件数を同じスナップショットから取得する。
        """テスト結果を除いた全体集計と難易度別件数を返す。"""
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    summary = await ResultRepository.get_non_test_statistics_summary(
                        cursor
                    )
                    rows = await ResultRepository.get_non_test_statistics_counts_grouped_by_difficulty(
                        cursor
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        summary["difficulties"] = {row["difficulty"]: row["count"] for row in rows}
        return summary

    @staticmethod
    async def history():
        """最新10件の宝探し履歴を取得する。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await ResultRepository.get_latest_10_statistics(cursor)

    @staticmethod
    async def admin_logs():
        """最新10件の管理者操作ログを取得する。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            return await AdminLogRepository.get_latest_10_admin_logs(cursor)

    @staticmethod
    async def delete_test(admin_id, admin_name):
        """テスト履歴の削除と管理ログ保存をまとめて確定する。"""
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    deleted = await ResultRepository.delete_test_statistics(cursor)
                    await AdminLogRepository.insert_admin_log(
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
