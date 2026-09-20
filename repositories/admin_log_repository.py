class AdminLogRepository:
    @staticmethod
    async def insert_admin_log(cursor, admin_id, admin_name, action, detail):
        """管理者の操作内容をadmin_logsに1件追加する。"""
        await cursor.execute(
            "INSERT INTO admin_logs (admin_id, admin_name, action, detail) VALUES (%s, %s, %s, %s)",
            (admin_id, admin_name, action, detail),
        )

    @staticmethod
    async def get_latest_10_admin_logs(cursor):
        """admin_logsからIDの降順で最新10件を取得する。"""
        await cursor.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 10")
        return await cursor.fetchall()
