class AdminLogRepository:
    def __init__(self, database):
        self.database = database

    async def recent(self):
        async with self.database.transaction() as cursor:
            await cursor.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 10")
            return await cursor.fetchall()
