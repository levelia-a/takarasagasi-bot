"""Discordの表示処理から独立した宝探しのルール。"""

import asyncio
import random
from dataclasses import dataclass, field
from uuid import uuid4

from consts.treasure import DIFFICULTIES
from repositories.result_repository import ResultRepository
from services.db_service import DbService
from services.progress_service import ProgressService
from services.settings_service import SettingsService


class TreasureStopped(ValueError):
    pass


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
    result: str | None = None
    unlocked_difficulty: str | None = None
    settings: dict = field(default_factory=dict, repr=False)
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
    async def create(user_id, user_name, difficulty):
        """運営状態と設定を確認し、開始時の設定を固定した探索を作る。"""
        if difficulty not in DIFFICULTIES:
            raise ValueError("不明な難易度です。")
        settings = await SettingsService.get_all()
        SettingsService.validate_settings(settings)
        if not settings["operation"]:
            raise TreasureStopped("現在、宝探しは停止中です。")
        # 難易度解放システム：中級・上級は開始前にユーザー進捗を確認する。
        await ProgressService.require_unlocked(user_id, difficulty, settings)
        return Exploration(
            user_id,
            user_name,
            difficulty,
            settings[f"{difficulty}_price"],
            settings[f"{difficulty}_rate"],
            settings[f"{difficulty}_max"],
            settings["test_mode"],
            settings=settings,
        )

    @staticmethod
    async def explore(session):
        """探索を1回進め、報酬を計算し、終了した場合は結果を保存する。"""
        async with session.lock:
            if session.result is not None:
                # 保存直前に通信が途切れた場合も、同じ結果を再試行できる。
                await TreasureService.save_result(session)
                return session
            session.exploration_count += 1
            # 難易度解放システム：実際の探索判定ごとに1回加算する。
            # 保存に失敗した場合は同じ探索番号を再試行し、DB側の探索IDで二重加算を防ぐ。
            # 管理者のテストモードではユーザー進捗を増やさない。
            if not session.is_test:
                exploration_id = f"{session.id}:{session.exploration_count}"
                try:
                    unlocked = await ProgressService.record_exploration(
                        session.user_id, session.difficulty, exploration_id
                    )
                except BaseException:
                    session.exploration_count -= 1
                    raise
                if unlocked:
                    session.unlocked_difficulty = unlocked
            success = session.test_mode == "always_success" or (
                session.test_mode == "normal" and random.randint(1, 100) <= session.rate
            )
            if success:
                session.success_count += 1
                session.reward = session.price * (2**session.success_count)
                if session.exploration_count >= session.max_exploration:
                    session.result = "max_success"
            else:
                session.reward = 0
                session.result = "failure"
            if session.result is not None:
                await TreasureService.save_result(session)
            return session

    @staticmethod
    async def retreat(session):
        """引き返して現在の報酬を確定し、結果を保存する。"""
        async with session.lock:
            if session.result is None:
                session.result = "retreat"
            await TreasureService.save_result(session)
            return session

    @staticmethod
    async def save_result(session):
        """探索結果をDB保存用に整形し、セッション単位で重複なく保存する。"""
        result = {
            "session_id": session.id,
            "user_id": session.user_id,
            "user_name": session.user_name,
            "difficulty": session.difficulty_name,
            "start_price": session.price,
            "success_count": session.success_count,
            "final_reward": session.reward,
            "result": session.result,
            "failure_point": session.exploration_count
            if session.result == "failure"
            else None,
            "is_test": session.is_test,
        }
        # 単一INSERTなのでautocommitで保存する。
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await ResultRepository.insert_statistics_record_if_session_id_not_exists(
                cursor, result
            )
