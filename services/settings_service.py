import asyncio

from consts.treasure import DIFFICULTIES, MAX_REWARD, TEST_MODES


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
    def __init__(self, repository):
        self.repository = repository
        self.lock = asyncio.Lock()

    async def get_all(self):
        return await self.repository.get_all()

    async def update(self, values, admin_id, admin_name, action):
        async with self.lock:
            settings = await self.repository.get_all()
            if not values.keys() <= settings.keys():
                raise ValueError("不明な設定項目です。")
            settings.update(values)
            validate_settings(settings)
            detail = ", ".join(f"{key}={value}" for key, value in values.items())
            await self.repository.update_with_log(
                values, admin_id, admin_name, action, detail
            )

    async def toggle_operation(self, admin_id, admin_name):
        async with self.lock:
            current = await self.repository.get_all()
            value = 0 if current["operation"] else 1
            await self.repository.update_with_log(
                {"operation": value},
                admin_id,
                admin_name,
                "運営ON/OFF変更",
                f"{current['operation']} → {value}",
            )
            return value
