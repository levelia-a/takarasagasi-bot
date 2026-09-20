from consts.treasure import DEFAULT_SETTINGS


class SettingsRepository:
    def __init__(self, database):
        self.database = database

    async def get_all(self):
        async with self.database.transaction() as cursor:
            await cursor.execute("SELECT `key`, value FROM settings")
            rows = await cursor.fetchall()
        settings = DEFAULT_SETTINGS.copy()
        for row in rows:
            key, value = row["key"], row["value"]
            if key in settings:
                settings[key] = value if key == "test_mode" else int(value)
        return settings

    async def update_with_log(self, values, admin_id, admin_name, action, detail):
        async with self.database.transaction() as cursor:
            for key, value in values.items():
                await cursor.execute(
                    "INSERT INTO settings (`key`, value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE value = %s",
                    (key, str(value), str(value)),
                )
            await cursor.execute(
                "INSERT INTO admin_logs (admin_id, admin_name, action, detail) VALUES (%s, %s, %s, %s)",
                (admin_id, admin_name, action, detail),
            )
