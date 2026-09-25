"""パーティーの永続化。同じサーバーの変更は行ロックで直列化する。"""


class PartyRepository:
    @staticmethod
    async def get_guild_lock_for_update(cursor, guild_id):
        await cursor.execute(
            # INSERT IGNOREの共有ロックから排他ロックへの昇格競合を避ける。
            "INSERT INTO party_guild_locks (guild_id) VALUES (%s) ON DUPLICATE KEY UPDATE guild_id = %s",
            (guild_id, guild_id),
        )
        await cursor.execute(
            "SELECT guild_id FROM party_guild_locks WHERE guild_id = %s FOR UPDATE",
            (guild_id,),
        )
        await cursor.fetchone()

    @staticmethod
    async def get_parties_by_guild_id(cursor, guild_id):
        await cursor.execute(
            """SELECT p.id, p.channel_id, p.leader_id,
               CASE WHEN s.run_id <> '' AND s.expires_at <= NOW() THEN ''
                    ELSE COALESCE(s.confirmation_id, '') END AS confirmation_id,
               CASE WHEN s.expires_at > NOW() THEN COALESCE(s.run_id, '') ELSE '' END AS run_id
               FROM parties p LEFT JOIN party_states s ON s.party_id = p.id
               WHERE p.guild_id = %s ORDER BY p.created_at, p.id""",
            (guild_id,),
        )
        parties = await cursor.fetchall()
        await cursor.execute(
            "SELECT party_id, user_id FROM party_members WHERE guild_id = %s ORDER BY joined_at, user_id",
            (guild_id,),
        )
        return parties, await cursor.fetchall()

    @staticmethod
    async def save_party_changes(cursor, guild_id, before, after):
        """所属削除を先に行い、一人一所属の一意制約を維持する。"""
        for party_id, party in before.items():
            remaining = after[party_id].members if party_id in after else ()
            for user_id in set(party.members) - set(remaining):
                await cursor.execute(
                    "DELETE FROM party_members WHERE guild_id = %s AND user_id = %s AND party_id = %s",
                    (guild_id, user_id, party_id),
                )
            if party_id not in after:
                await cursor.execute(
                    "DELETE FROM party_states WHERE party_id = %s", (party_id,)
                )
                await cursor.execute(
                    "DELETE FROM parties WHERE id = %s AND guild_id = %s",
                    (party_id, guild_id),
                )
        for party_id, party in after.items():
            old = before.get(party_id)
            if old is None:
                await cursor.execute(
                    "INSERT INTO parties (id, guild_id, channel_id, leader_id) VALUES (%s, %s, %s, %s)",
                    (party_id, guild_id, party.channel_id, party.leader_id),
                )
            elif old.leader_id != party.leader_id:
                await cursor.execute(
                    "UPDATE parties SET leader_id = %s WHERE id = %s AND guild_id = %s",
                    (party.leader_id, party_id, guild_id),
                )
            if old is None or (old.confirmation_id, old.run_id) != (
                party.confirmation_id,
                party.run_id,
            ):
                await cursor.execute(
                    """INSERT INTO party_states (party_id, confirmation_id, run_id, expires_at)
                       VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE))
                       ON DUPLICATE KEY UPDATE confirmation_id = %s, run_id = %s,
                       expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE)""",
                    (
                        party_id,
                        party.confirmation_id,
                        party.run_id,
                        party.confirmation_id,
                        party.run_id,
                    ),
                )
            for user_id in party.members:
                if old is None or user_id not in old.members:
                    await cursor.execute(
                        "INSERT INTO party_members (guild_id, user_id, party_id) VALUES (%s, %s, %s)",
                        (guild_id, user_id, party_id),
                    )
