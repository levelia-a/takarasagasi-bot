"""Discordの表示処理から独立した宝探しのルール。"""

import asyncio
import random
from dataclasses import dataclass, field
from uuid import uuid4

from consts.treasure import DIFFICULTIES
from services.settings_service import validate_settings


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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def difficulty_name(self):
        return DIFFICULTIES[self.difficulty]["name"]

    @property
    def is_test(self):
        return self.test_mode != "normal"


class TreasureService:
    def __init__(self, db, settings_service, result_repository, randint=None):
        self.db = db
        self.settings = settings_service
        self.results = result_repository
        self.randint = randint or random.randint

    async def create(self, user_id, user_name, difficulty):
        if difficulty not in DIFFICULTIES:
            raise ValueError("不明な難易度です。")
        settings = await self.settings.get_all()
        validate_settings(settings)
        if not settings["operation"]:
            raise TreasureStopped("現在、宝探しは停止中です。")
        return Exploration(
            user_id,
            user_name,
            difficulty,
            settings[f"{difficulty}_price"],
            settings[f"{difficulty}_rate"],
            settings[f"{difficulty}_max"],
            settings["test_mode"],
        )

    async def explore(self, session):
        async with session.lock:
            if session.result is not None:
                # 保存直前に通信が途切れた場合も、同じ結果を再試行できる。
                await self.save_result(session)
                return session
            session.exploration_count += 1
            success = session.test_mode == "always_success" or (
                session.test_mode == "normal" and self.randint(1, 100) <= session.rate
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
                await self.save_result(session)
            return session

    async def retreat(self, session):
        async with session.lock:
            if session.result is None:
                session.result = "retreat"
            await self.save_result(session)
            return session

    async def save_result(self, session):
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
            self.db.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await self.results.save(cursor, result)
