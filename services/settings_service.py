import asyncio

from consts.treasure import DEFAULT_SETTINGS, DIFFICULTIES, MAX_REWARD, TEST_MODES
from consts.balance import CATALOG_SETTING_KEYS
from consts.cooperation import EVENT_TEXT_KEYS
from consts.stages import LEGACY_STAGE_KEYS
from services.balance_service import BalanceService
from services.cooperation_service import CooperationService
from repositories.admin_log_repository import AdminLogRepository
from repositories.settings_repository import SettingsRepository
from services.db_service import DbService
from services.treasure_catalog_service import TreasureCatalogService


class SettingsService:
    _lock = asyncio.Lock()

    @staticmethod
    def validate_settings(settings, catalog=None):
        """設定値の範囲を検証し、不正な場合はValueErrorを送出する。"""
        BalanceService.validate(settings)
        CooperationService.validate(settings)
        if settings["test_mode"] not in TEST_MODES:
            raise ValueError("不明なテストモードです。")
        if settings["operation"] not in (0, 1):
            raise ValueError("運営状態は0または1で指定してください。")
        # 難易度解放システム：管理者が設定する必要探索回数を検証する。
        for unlock_key in ("intermediate_unlock", "advanced_unlock"):
            if not 1 <= settings[unlock_key] <= 1000000:
                raise ValueError("解放条件は1〜1,000,000回にしてください。")
        for key in DIFFICULTIES:
            price, rate, maximum = (
                settings[f"{key}_{suffix}"] for suffix in ("price", "rate", "max")
            )
            if not 0 <= price <= MAX_REWARD:
                raise ValueError("挑戦料は0以上・65桁以内にしてください。")
            if not 0 <= rate <= 100:
                raise ValueError("成功率は0〜100にしてください。")
            if not 1 <= maximum <= 215:
                raise ValueError("最大探索回数は1〜215にしてください。")
        if catalog is None:
            catalog = TreasureCatalogService.load_catalog()
        catalog = BalanceService.apply_catalog(catalog, settings)
        for key in DIFFICULTIES:
            TreasureCatalogService.validate_reward_limit(
                catalog[key], CooperationService.maximum(settings[f"{key}_max"], settings)
            )

    @staticmethod
    def build_settings(rows):
        """設定行の型を変換し、未登録項目を初期値で補完する。"""
        settings = DEFAULT_SETTINGS.copy()
        values = {row['key']: row['value'] for row in rows}
        for old, new in LEGACY_STAGE_KEYS.items():
            if new not in values and old in values:
                values[new] = values[old]
        for key, value in values.items():
            if key in settings:
                settings[key] = value if key == "test_mode" or key in CATALOG_SETTING_KEYS or key in EVENT_TEXT_KEYS else int(value)
        return settings

    @staticmethod
    async def get_all():
        """DBの設定を取得し、初期値で補完した設定辞書を返す。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            rows = await SettingsRepository.get_all_settings(cursor)
        return SettingsService.build_settings(rows)

    @staticmethod
    async def update(values, admin_id, admin_name, action):
        """変更値を検証し、設定更新と管理ログ保存をまとめて確定する。"""
        async with SettingsService._lock, DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    rows = await SettingsRepository.get_all_settings_for_update(cursor)
                    settings = SettingsService.build_settings(rows)
                    if not values.keys() <= settings.keys():
                        raise ValueError("不明な設定項目です。")
                    settings.update(values)
                    SettingsService.validate_settings(settings)
                    for key, value in values.items():
                        await SettingsRepository.upsert_setting_by_key(
                            cursor, key, str(value)
                        )
                    detail = ", ".join(
                        f"{key}={value}" for key, value in values.items()
                    )
                    await AdminLogRepository.insert_admin_log(
                        cursor, admin_id, admin_name, action, detail
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    @staticmethod
    async def toggle_operation(admin_id, admin_name):
        """運営状態と管理ログをまとめて保存し、新しい状態を返す。"""
        async with SettingsService._lock, DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    rows = await SettingsRepository.get_all_settings_for_update(cursor)
                    current = SettingsService.build_settings(rows)
                    value = 0 if current["operation"] else 1
                    await SettingsRepository.upsert_setting_by_key(
                        cursor, "operation", str(value)
                    )
                    await AdminLogRepository.insert_admin_log(
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
