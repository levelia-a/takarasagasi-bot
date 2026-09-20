"""秘密情報と接続設定を環境変数から読み込む。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

from consts.discord import DEFAULT_GUILD_ID


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str

    @classmethod
    def from_env(cls):
        """環境変数からMySQLの接続設定を読み込み、必須項目を検証する。"""
        load_dotenv(Path(__file__).with_name(".env"))
        url = os.getenv("MYSQL_URL", "")
        if url:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "mysql"
                or not parsed.hostname
                or not parsed.username
                or not parsed.path.strip("/")
            ):
                raise ValueError(
                    "MYSQL_URL は mysql://user:password@host:port/database 形式で指定してください。"
                )
            if parsed.query or parsed.fragment:
                raise ValueError(
                    "MYSQL_URL のクエリパラメータとフラグメントには対応していません。"
                )
            return cls(
                parsed.hostname,
                parsed.port or 3306,
                unquote(parsed.username),
                unquote(parsed.password or ""),
                unquote(parsed.path.lstrip("/")),
            )
        host = os.getenv("MYSQLHOST") or os.getenv("MYSQL_HOST")
        user = os.getenv("MYSQLUSER") or os.getenv("MYSQL_USER")
        database = os.getenv("MYSQL_DATABASE")
        missing = [
            name
            for name, value in (
                ("MYSQLHOST", host),
                ("MYSQLUSER", user),
                ("MYSQL_DATABASE", database),
            )
            if not value
        ]
        if missing:
            raise ValueError("必須環境変数が未設定です: " + ", ".join(missing))
        port = int(os.getenv("MYSQLPORT") or os.getenv("MYSQL_PORT", "3306"))
        if not 1 <= port <= 65535:
            raise ValueError("MYSQLPORT は1〜65535で指定してください。")
        return cls(
            host,
            port,
            user,
            os.getenv("MYSQLPASSWORD", os.getenv("MYSQL_PASSWORD", "")),
            database,
        )


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    guild_id: int
    database: DatabaseConfig

    @classmethod
    def from_env(cls):
        """Botトークン・サーバーID・DB接続設定を読み込む。"""
        database = DatabaseConfig.from_env()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN が未設定です。")
        guild_id = int(
            os.getenv("GUILD_ID") or os.getenv("DISCORD_GUILD_ID") or DEFAULT_GUILD_ID
        )
        if guild_id <= 0:
            raise ValueError("GUILD_ID は正の整数で指定してください。")
        return cls(token, guild_id, database)
