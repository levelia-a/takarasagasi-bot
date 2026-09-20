import asyncio

from consts.treasure import DEFAULT_SETTINGS, DIFFICULTIES, MAX_REWARD, TEST_MODES


def validate_settings(settings):
    if settings["test_mode"] not in TEST_MODES:
        raise ValueError("不明なテストモードです。")
    if settings["operation"] not in (0, 1):
        raise ValueError("運営状態は0または1で指定してください。")
    for key in DIFFICULTIES:
        price, rate, maximum = (
            settings[f"{key}_{suffix}"] for suffix in ("price", "rate", "max")
        )
        if price < 0:
            raise ValueError("価格は0以上にしてください。")
        if not 0 <= rate <= 100:
            raise ValueError("成功率は0〜100にしてください。")
        if not 1 <= maximum <= 215:
            raise ValueError("最大探索回数は1〜215にしてください。")
        if price * (2**maximum) > MAX_REWARD:
            raise ValueError(
                "最大報酬がMySQLの保存上限（65桁）を超えています。価格か探索回数を下げてください。"
            )


class SettingsService:
    def __init__(self, db, repository, logs):
        self.db = db
        self.repository = repository
        self.logs = logs
        self.lock = asyncio.Lock()

    @staticmethod
    def build_settings(rows):
        settings = DEFAULT_SETTINGS.copy()
        for row in rows:
            key, value = row["key"], row["value"]
            if key in settings:
                settings[key] = value if key == "test_mode" else int(value)
        return settings

    async def get_all(self):
        async with (
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            rows = await self.repository.get_all(cursor)
        return self.build_settings(rows)

    async def update(self, values, admin_id, admin_name, action):
        async with self.lock, self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    rows = await self.repository.get_all_for_update(cursor)
                    settings = self.build_settings(rows)
                    if not values.keys() <= settings.keys():
                        raise ValueError("不明な設定項目です。")
                    settings.update(values)
                    validate_settings(settings)
                    for key, value in values.items():
                        await self.repository.upsert(cursor, key, str(value))
                    detail = ", ".join(
                        f"{key}={value}" for key, value in values.items()
                    )
                    await self.logs.insert(cursor, admin_id, admin_name, action, detail)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def toggle_operation(self, admin_id, admin_name):
        async with self.lock, self.db.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    rows = await self.repository.get_all_for_update(cursor)
                    current = self.build_settings(rows)
                    value = 0 if current["operation"] else 1
                    await self.repository.upsert(cursor, "operation", str(value))
                    await self.logs.insert(
                        cursor,
                        admin_id,
                        admin_name,
                        "運営ON/OFF変更",
                        f"{current['operation']} → {value}",
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        return value
