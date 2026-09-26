"""ゲーム内ギルドの保存。Discordサーバー単位で変更を直列化する。"""


class GuildRepository:
    @staticmethod
    async def lock(cursor, server_id):
        await cursor.execute(
            "INSERT INTO game_guild_locks (server_id) VALUES (%s) "
            "ON DUPLICATE KEY UPDATE server_id = %s",
            (server_id, server_id),
        )
        await cursor.execute(
            "SELECT server_id FROM game_guild_locks WHERE server_id = %s FOR UPDATE",
            (server_id,),
        )
        await cursor.fetchone()

    @staticmethod
    async def load(cursor, server_id):
        await cursor.execute(
            "SELECT * FROM game_guilds WHERE server_id = %s", (server_id,)
        )
        guilds = await cursor.fetchall()
        await cursor.execute(
            "SELECT * FROM game_guild_members WHERE server_id = %s ORDER BY user_id",
            (server_id,),
        )
        return guilds, await cursor.fetchall()

    @staticmethod
    async def save(cursor, server_id, before, after):
        # 所属削除を先行し、一人一所属の主キーを常に維持する。
        for gid, guild in before.items():
            members = after[gid].members if gid in after else ()
            for member in guild.members:
                if member not in members:
                    await cursor.execute(
                        "DELETE FROM game_guild_members WHERE server_id = %s AND user_id = %s",
                        (server_id, member.user_id),
                    )
            if gid not in after:
                await cursor.execute("DELETE FROM game_guilds WHERE id = %s", (gid,))
        for gid, guild in after.items():
            previous = before.get(gid)
            if previous is None:
                await cursor.execute(
                    "INSERT INTO game_guilds (id, server_id, name, passphrase_hash, leader_id) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        gid,
                        server_id,
                        guild.name,
                        guild.passphrase_hash,
                        guild.leader_id,
                    ),
                )
            elif previous.leader_id != guild.leader_id:
                await cursor.execute(
                    "UPDATE game_guilds SET leader_id = %s WHERE id = %s",
                    (guild.leader_id, gid),
                )
            for member in guild.members:
                if previous is None or member not in previous.members:
                    await cursor.execute(
                        "INSERT INTO game_guild_members "
                        "(server_id, user_id, game_guild_id, server_joined_at) VALUES (%s, %s, %s, %s)",
                        (server_id, member.user_id, gid, member.server_joined_at),
                    )
