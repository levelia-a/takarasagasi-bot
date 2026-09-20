class SettingsRepository:
    async def get_all_settings(self, cursor):
        """settingsからすべての設定行を取得する。"""
        await cursor.execute("SELECT `key`, value FROM settings")
        return await cursor.fetchall()

    async def get_all_settings_for_update(self, cursor):
        """settingsの設定行を更新用にロックして取得する。"""
        await cursor.execute("SELECT `key`, value FROM settings FOR UPDATE")
        return await cursor.fetchall()

    async def upsert_setting_by_key(self, cursor, key, value):
        """指定キーの設定を追加し、存在する場合は値を更新する。"""
        await cursor.execute(
            "INSERT INTO settings (`key`, value) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE value = %s",
            (key, value, value),
        )
