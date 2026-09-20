"""MySQL接続プールの管理。トランザクションの範囲は呼び出し側で決める。"""

from contextlib import asynccontextmanager

import aiomysql

from config import DatabaseConfig


class DbService:
    _pool: aiomysql.Pool | None = None

    @staticmethod
    async def connect(config: DatabaseConfig):
        """MySQLの接続プールを作成する。"""
        if DbService._pool is not None:
            raise RuntimeError("MySQLの接続プールは作成済みです。")
        DbService._pool = await aiomysql.create_pool(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            db=config.database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=aiomysql.DictCursor,
            minsize=1,
            maxsize=5,
            connect_timeout=10,
            pool_recycle=300,
            init_command="SET time_zone = '+09:00'",
        )

    @staticmethod
    @asynccontextmanager
    async def get_connection():
        """プールから接続を貸し出し、処理終了時に解放する。"""
        if DbService._pool is None:
            raise RuntimeError("MySQLに接続していません。")
        async with DbService._pool.acquire() as connection:
            yield connection

    @staticmethod
    async def close():
        """接続の解放を待ち、DB接続プールを終了する。"""
        if DbService._pool is not None:
            DbService._pool.close()
            await DbService._pool.wait_closed()
            DbService._pool = None
