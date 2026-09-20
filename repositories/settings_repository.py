class SettingsRepository:
    async def get_all_settings(self, cursor):
        await cursor.execute("SELECT `key`, value FROM settings")
        return await cursor.fetchall()

    async def get_all_settings_for_update(self, cursor):
        await cursor.execute("SELECT `key`, value FROM settings FOR UPDATE")
        return await cursor.fetchall()

    async def upsert_setting_by_key(self, cursor, key, value):
        await cursor.execute(
            "INSERT INTO settings (`key`, value) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE value = %s",
            (key, value, value),
        )
