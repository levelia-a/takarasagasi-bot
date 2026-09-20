"""MySQL接続プールの管理。トランザクションの範囲は呼び出し側で決める。"""

from contextlib import asynccontextmanager

import aiomysql

from config import DatabaseConfig


class DbService:
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.pool = None

    async def connect(self):
        self.pool = await aiomysql.create_pool(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            db=self.config.database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=aiomysql.DictCursor,
            minsize=1,
            maxsize=5,
            connect_timeout=10,
            pool_recycle=300,
            init_command="SET time_zone = '+09:00'",
        )

    @asynccontextmanager
    async def get_connection(self):
        if self.pool is None:
            raise RuntimeError("MySQLに接続していません。")
        async with self.pool.acquire() as connection:
            yield connection

    async def close(self):
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
