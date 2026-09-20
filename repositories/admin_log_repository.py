class AdminLogRepository:
    async def insert(self, cursor, admin_id, admin_name, action, detail):
        await cursor.execute(
            "INSERT INTO admin_logs (admin_id, admin_name, action, detail) VALUES (%s, %s, %s, %s)",
            (admin_id, admin_name, action, detail),
        )

    async def recent(self, cursor):
        await cursor.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 10")
        return await cursor.fetchall()
