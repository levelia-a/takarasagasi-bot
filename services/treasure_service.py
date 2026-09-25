"""Discordの表示処理から独立した宝探しのルール。"""

import asyncio
import random
from dataclasses import dataclass, field
from uuid import uuid4

from consts.treasure import DIFFICULTIES
from consts.maps import MAPS
from services.map_service import MapService
from services.stage_service import StageService
from services.balance_service import BalanceService
from services.cooperation_service import CooperationBonus, CooperationService
from repositories.active_exploration_repository import ActiveExplorationRepository
from repositories.result_repository import ResultRepository
from services.db_service import DbService
from services.progress_service import ProgressService
from services.settings_service import SettingsService
from services.treasure_catalog_service import Treasure, TreasureCatalogService


class TreasureStopped(ValueError):
    pass


class TreasureAlreadyActive(ValueError):
    pass


@dataclass(frozen=True)
class FoundTreasure:
    key: str
    name: str
    price: int
    exploration_number: int
    rarity: str = 'normal'


@dataclass
class Exploration:
    user_id: int
    user_name: str
    difficulty: str
    price: int
    rate: int
    max_exploration: int
    test_mode: str
    id: str = field(default_factory=lambda: str(uuid4()))
    exploration_count: int = 0
    success_count: int = 0
    reward: int = 0
    found_treasures: list[FoundTreasure] = field(default_factory=list)
    treasure_pool: tuple[Treasure, ...] = field(default_factory=tuple, repr=False)
    result: str | None = None
    unlocked_difficulty: str | None = None
    pending_exploration_id: str | None = None
    map_tier: str = 'normal'
    stage: str = 'forest'
    settings: dict = field(default_factory=dict, repr=False)
    cooperation: CooperationBonus = field(default_factory=CooperationBonus)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def difficulty_name(self):
        """探索の難易度に対応する日本語名を返す。"""
        return DIFFICULTIES[self.difficulty]["name"]

    @property
    def is_test(self):
        """通常確率以外のテストモードで開始した探索かを返す。"""
        return self.test_mode != "normal"


class TreasureService:
    @staticmethod
    async def _claim_user(user_id, session_id):
        """MySQLの一意制約で、プロセスをまたいで1ユーザー1セッションを保証する。"""
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            claimed = await ActiveExplorationRepository.claim(
                cursor, user_id, session_id
            )
        if not claimed:
            raise TreasureAlreadyActive(
                "進行中の宝探しがあります。先にその探索を完了してください。"
            )

    @staticmethod
    async def _refresh_user(session):
        """操作中セッションのDBロック期限を延長する。"""
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            await ActiveExplorationRepository.refresh(
                cursor, session.user_id, session.id
            )

    @staticmethod
    async def release_user(user_id, session_id):
        """指定セッションが所有するDBロックだけを解放する。"""
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            await ActiveExplorationRepository.release(cursor, user_id, session_id)

    @staticmethod
    async def create(user_id, user_name, difficulty, *, vc_members=0):
        """運営状態と設定を確認し、開始時の設定を固定した探索を作る。"""
        if difficulty not in DIFFICULTIES:
            raise ValueError("不明な難易度です。")
        settings = dict(await SettingsService.get_all())
        catalog = TreasureCatalogService.load_catalog()
        SettingsService.validate_settings(settings, catalog=catalog)
        catalog = BalanceService.apply_catalog(catalog, settings)
        if not settings["operation"]:
            raise TreasureStopped("現在、宝探しは停止中です。")
        # 難易度解放システム：中級・上級は開始前にユーザー進捗を確認する。
        unlock_notice = await ProgressService.require_unlocked(
            user_id, difficulty, settings
        )
        treasure_pool = TreasureCatalogService.require_available(catalog, difficulty)
        session_id = str(uuid4())
        await TreasureService._claim_user(user_id, session_id)
        try:
            return TreasureService.build_session(
                user_id, user_name, difficulty, settings, treasure_pool,
                vc_members=vc_members, session_id=session_id, unlock_notice=unlock_notice,
            )
        except BaseException:
            await TreasureService.release_user(user_id, session_id)
            raise

    @staticmethod
    def build_session(user_id, user_name, difficulty, settings, treasure_pool, *,
                      vc_members, session_id, unlock_notice=None):
        """個人・共有探索で同じ開始時抽選を使う。呼び出し側で開始枠を確保する。"""
        map_tier = MapService.draw(settings)
        stage = StageService.draw(settings)
        cooperation = CooperationService.draw(vc_members, settings, settings[f'{difficulty}_max'])
        treasure_pool = CooperationService.apply_pool(treasure_pool, cooperation)
        return Exploration(
            user_id,
            user_name,
            difficulty,
            settings[f"{difficulty}_price"],
            min(100, settings[f"{difficulty}_rate"] + (settings[f'map_{map_tier}_bonus'] if map_tier != 'normal' else 0) + cooperation.rate_bonus),
            settings[f"{difficulty}_max"] + cooperation.extra,
            settings["test_mode"],
            id=session_id,
            map_tier=map_tier,
            stage=stage,
            unlocked_difficulty=unlock_notice,
            settings=settings,
            cooperation=cooperation,
            treasure_pool=treasure_pool,
        )

    @staticmethod
    async def explore(session):
        """探索を1回進め、進捗と終了結果を整合性を保って保存する。"""
        async with session.lock:
            await TreasureService._refresh_user(session)
            # 前回のDB保存が失敗した場合は、同じ探索を再抽選せず保存だけ再試行する。
            if session.pending_exploration_id is not None:
                result = (
                    TreasureService.build_result(session) if session.result else None
                )
                unlocked = await ProgressService.record_exploration(
                    session.user_id,
                    session.difficulty,
                    session.pending_exploration_id,
                    result,
                    session_id=session.id,
                )
                if unlocked:
                    session.unlocked_difficulty = unlocked
                session.pending_exploration_id = None
                return session

            if session.result is not None:
                await TreasureService.save_result(session)
                return session

            TreasureService.roll(session)

            if not session.is_test:
                session.pending_exploration_id = (
                    f"{session.id}:{session.exploration_count}"
                )
                result = (
                    TreasureService.build_result(session) if session.result else None
                )
                unlocked = await ProgressService.record_exploration(
                    session.user_id,
                    session.difficulty,
                    session.pending_exploration_id,
                    result,
                    session_id=session.id,
                )
                if unlocked:
                    session.unlocked_difficulty = unlocked
                session.pending_exploration_id = None
            elif session.result is not None:
                await TreasureService.save_result(session)
            return session

    @staticmethod
    def roll(session):
        """awaitせず1回分の共通判定・宝物・終了状態を確定する。"""
        success = session.test_mode == "always_success" or (
            session.test_mode == "normal" and random.randint(1, 100) <= session.rate
        )
        # ここからpending ID設定まではawaitせず、判定と宝物を一度だけ確定する。
        treasure = TreasureCatalogService.draw(session.treasure_pool, session.stage, session.settings) if success else None
        session.exploration_count += 1
        if success:
            session.found_treasures.append(FoundTreasure(
                treasure.key, treasure.name, treasure.price, session.exploration_count, treasure.rarity
            ))
            session.success_count += 1
            session.reward = sum(item.price for item in session.found_treasures)
            if session.exploration_count >= session.max_exploration:
                session.result = "max_success"
        else:
            session.reward = 0
            session.result = "failure"

    @staticmethod
    async def retreat(session):
        """引き返し時も未確定の探索進捗と最終結果を同一transactionで確定する。"""
        async with session.lock:
            await TreasureService._refresh_user(session)
            if session.result is None:
                session.result = "retreat"

            if not session.is_test and session.pending_exploration_id is not None:
                unlocked = await ProgressService.record_exploration(
                    session.user_id,
                    session.difficulty,
                    session.pending_exploration_id,
                    TreasureService.build_result(session),
                    session_id=session.id,
                )
                if unlocked:
                    session.unlocked_difficulty = unlocked
                session.pending_exploration_id = None
            else:
                await TreasureService.save_result(session)

            return session

    @staticmethod
    def build_result(session):
        """現在の探索状態をDB保存用の結果辞書へ変換する。"""
        return {
            "session_id": session.id,
            "user_id": session.user_id,
            "user_name": session.user_name,
            "difficulty": session.difficulty_name,
            "start_price": session.price,
            "success_count": session.success_count,
            "final_reward": session.reward,
            "result": session.result,
            "failure_point": (
                session.exploration_count if session.result == "failure" else None
            ),
            "is_test": session.is_test,
        }

    @staticmethod
    async def save_result(session):
        """探索結果をセッションID単位で重複なく保存する。"""
        result = TreasureService.build_result(session)
        async with DbService.get_connection() as connection:
            await connection.begin()
            try:
                async with connection.cursor() as cursor:
                    await ActiveExplorationRepository.refresh(
                        cursor, session.user_id, session.id
                    )
                    await ResultRepository.insert_statistics_record_if_session_id_not_exists(
                        cursor, result
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
