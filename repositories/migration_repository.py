from uuid import NAMESPACE_URL, uuid5

from consts.treasure import DEFAULT_SETTINGS


class MigrationRepository:
    def __init__(self, database):
        self.database = database

    async def import_source(self, payload, digest):
        async with self.database.transaction() as cursor:
            # 同時に走った移行処理と設定更新を直列化する。
            await cursor.execute(
                "SELECT `key`, value FROM settings ORDER BY `key` FOR UPDATE"
            )
            current = {row["key"]: row["value"] for row in await cursor.fetchall()}
            await cursor.execute(
                "SELECT source_sha256 FROM data_migrations WHERE source_sha256 = %s",
                (digest,),
            )
            if await cursor.fetchone():
                return False
            for table in ("statistics", "admin_logs", "data_migrations"):
                await cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
                if (await cursor.fetchone())["count"]:
                    raise ValueError(
                        "移行先に既存データがあります。空の専用DBを指定してください。"
                    )
            if current != {key: str(value) for key, value in DEFAULT_SETTINGS.items()}:
                raise ValueError(
                    "移行先の設定が変更されています。空の専用DBを指定してください。"
                )
            for key, value in payload["settings"].items():
                await cursor.execute(
                    "UPDATE settings SET value = %s WHERE `key` = %s", (str(value), key)
                )
            for row in payload["records"]:
                session_id = str(
                    uuid5(NAMESPACE_URL, f"{digest}:{row['source_table']}:{row['id']}")
                )
                await cursor.execute(
                    "INSERT INTO statistics (session_id, user_id, user_name, difficulty, start_price, "
                    "success_count, final_reward, result, failure_point, is_test, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        session_id,
                        row["user_id"],
                        row["user_name"],
                        row["difficulty"],
                        row["start_price"],
                        row["success_count"],
                        row["final_reward"],
                        row["result"],
                        row.get("failure_point"),
                        row["is_test"],
                        row["created_at"],
                    ),
                )
            for row in payload["logs"]:
                await cursor.execute(
                    "INSERT INTO admin_logs (admin_id, admin_name, action, detail, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        row["admin_id"],
                        row["admin_name"],
                        row["action"],
                        row["detail"],
                        row["created_at"],
                    ),
                )
            await cursor.execute(
                "INSERT INTO data_migrations (source_sha256, detail) VALUES (%s, %s)",
                (
                    digest,
                    f"history={len(payload['records'])}, admin_logs={len(payload['logs'])}",
                ),
            )
        return True
