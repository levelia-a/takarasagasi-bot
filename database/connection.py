"""MySQL接続プールとトランザクションの管理。"""

from contextlib import asynccontextmanager

import aiomysql

from config import DatabaseConfig


class Database:
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
            autocommit=False,
            minsize=1,
            maxsize=5,
            connect_timeout=10,
            pool_recycle=300,
            init_command="SET time_zone = '+09:00'",
        )

    @asynccontextmanager
    async def transaction(self):
        if self.pool is None:
            raise RuntimeError("MySQLに接続していません。")
        async with self.pool.acquire() as connection:
            await connection.begin()
            try:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    yield cursor
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def close(self):
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
