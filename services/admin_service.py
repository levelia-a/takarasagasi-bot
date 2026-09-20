class AdminService:
    def __init__(self, results, logs):
        self.results = results
        self.logs = logs

    async def statistics(self):
        return await self.results.summary()

    async def history(self):
        return await self.results.recent()

    async def admin_logs(self):
        return await self.logs.recent()

    async def delete_test(self, admin_id, admin_name):
        return await self.results.delete_test_with_log(admin_id, admin_name)
