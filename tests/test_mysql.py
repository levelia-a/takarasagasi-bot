import asyncio
import os
import unittest
from unittest.mock import patch

from aiomysql import Connection
from pymysql.err import IntegrityError, OperationalError

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.tables import TABLES_SQL
from repositories.active_exploration_repository import (
    ActiveExplorationRepository,
    TreasureSessionExpired,
)
from repositories.settings_repository import SettingsRepository
from repositories.progress_repository import ProgressRepository
from repositories.result_repository import ResultRepository
from services.admin_service import AdminService
from services.db_service import DbService
from services.progress_service import ProgressService
from services.schema_service import SchemaService
from services.settings_service import SettingsService
from services.treasure_service import TreasureAlreadyActive, TreasureService
from tests.treasure_fixtures import install_test_catalog


@unittest.skipUnless(
    os.getenv("TAKARA_TEST_MYSQL_URL"), "使い捨てMySQLのURLが未指定です"
)
class MySQLTests(unittest.IsolatedAsyncioTestCase):
    async def test_balance_settings_persist_and_only_affect_new_games(self):
        with patch('services.treasure_service.MapService.draw', return_value='gold'):
            first = await TreasureService.create(801, 'old', 'beginner')
            await SettingsService.update({
                'map_gold_bonus': 30, 'color_green_multiplier': 250,
                'rarity_profile_enabled': 1,
                'treasure_beginner_probabilities': '15,15,15,15,15,8,7,5,4,1',
            }, 1, 'admin', 'バランス変更')
            restored = await SettingsService.get_all()
            self.assertEqual(restored['color_green_multiplier'], 250)
            self.assertEqual(restored['treasure_beginner_probabilities'], '15,15,15,15,15,8,7,5,4,1')
            second = await TreasureService.create(802, 'new', 'beginner')
        self.assertEqual(first.rate, 80)
        self.assertEqual(second.rate, 90)
        self.assertEqual(first.settings['color_green_multiplier'], 200)
        self.assertEqual(second.settings['color_green_multiplier'], 250)
        self.assertEqual(sum(t.probability for t in second.treasure_pool if t.rarity == 'normal'), 75)
        self.assertEqual(first.treasure_pool[0].probability, 10)
        self.assertEqual(len(await AdminService.admin_logs()), 1)
        with self.assertRaises(ValueError):
            await SettingsService.update({'color_red_chance': 301}, 1, 'admin', 'invalid')
        self.assertEqual((await SettingsService.get_all())['color_red_chance'], 300)
        self.assertEqual(len(await AdminService.admin_logs()), 1)

    async def test_history_user_filter_covers_all_pages_and_test_records(self):
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            for i in range(24):
                await ResultRepository.insert_statistics_record_if_session_id_not_exists(cursor, dict(
                    session_id=f'filtered-{i}', user_id=7 if i % 2 else 8,
                    user_name='same-name', difficulty='初級', start_price=0,
                    success_count=1, final_reward=100, result='retreat',
                    failure_point=None, is_test=(i // 2) % 2,
                ))
        first, more = await AdminService.history_page(user_id=7)
        self.assertEqual(len(first), 10)
        self.assertTrue(more)
        second, more = await AdminService.history_page(first[-1]['id'], user_id=7)
        self.assertEqual(len(second), 2)
        self.assertFalse(more)
        self.assertEqual({r['user_id'] for r in first + second}, {7})
        self.assertEqual({r['is_test'] for r in first + second}, {0, 1})
        self.assertEqual(len({r['id'] for r in first + second}), 12)
        self.assertEqual(await AdminService.history_page(user_id=999), ([], False))

    async def test_history_pages_remain_stable_after_new_record(self):
        async def insert_result(cursor, i):
            await ResultRepository.insert_statistics_record_if_session_id_not_exists(cursor, dict(
                session_id=f'history-{i}', user_id=1, user_name='user', difficulty='初級',
                start_price=0, success_count=1, final_reward=100, result='retreat',
                failure_point=None, is_test=i % 2,
            ))
        self.assertEqual(await AdminService.history_page(), ([], False))
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            for i in range(21):
                await insert_result(cursor, i)
        first, more = await AdminService.history_page()
        self.assertEqual(len(first), 10)
        self.assertTrue(more)
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            await insert_result(cursor, 21)
        second, more = await AdminService.history_page(first[-1]['id'])
        self.assertEqual(len(second), 10)
        self.assertTrue(more)
        third, more = await AdminService.history_page(second[-1]['id'])
        self.assertEqual(len(third), 1)
        self.assertFalse(more)
        self.assertEqual(len({r['id'] for r in first + second + third}), 21)

    async def test_rankings_aggregate_and_persist_panel(self):
        from services.ranking_service import RankingService
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            for sid, uid, successes, reward, test in (
                ('r1', 1, 2, 100, 0), ('r2', 1, 3, 0, 0),
                ('r3', 2, 5, 200, 0), ('r4', 1, 99, 9999, 1),
            ):
                result = dict(session_id=sid, user_id=uid, user_name='test',
                              difficulty='初級', start_price=1000, success_count=successes,
                              final_reward=reward, result='retreat' if reward else 'failure',
                              failure_point=None, is_test=test)
                await ResultRepository.insert_statistics_record_if_session_id_not_exists(cursor, result)
                await ResultRepository.insert_statistics_record_if_session_id_not_exists(cursor, result)
        snapshot = await RankingService.refresh()
        success = [e for e in snapshot.entries if e.metric == 'successes']
        self.assertEqual([(e.user_id, e.value, e.position) for e in success], [(1, 5, 1), (2, 5, 1)])
        for metric in ('payout', 'best'):
            self.assertEqual([(e.user_id, e.value) for e in snapshot.entries if e.metric == metric], [(2, 200), (1, 100)])
        self.assertIsNone(await RankingService.get_panel())
        await RankingService.save_panel(1, 2, 3)
        self.assertEqual(await RankingService.get_panel(), [1, 2, 3])
        await RankingService.save_panel(1, 2, 4)
        self.assertEqual(await RankingService.get_panel(), [1, 2, 4])

    async def test_ranking_top_10_excludes_zero_and_keeps_exact_amounts(self):
        from services.ranking_service import RankingService
        async with DbService.get_connection() as connection, connection.cursor() as cursor:
            for uid in range(13):
                await ResultRepository.insert_statistics_record_if_session_id_not_exists(cursor, dict(
                    session_id=f'top-{uid}', user_id=uid, user_name='user', difficulty='上級',
                    start_price=0, success_count=uid, final_reward=(10**60 + uid) if uid else 0,
                    result='retreat', failure_point=None, is_test=0,
                ))
        snapshot = await RankingService.refresh()
        for metric in ('successes', 'payout', 'best'):
            entries = [e for e in snapshot.entries if e.metric == metric]
            self.assertEqual([e.user_id for e in entries], list(range(12, 2, -1)))
            if metric != 'successes':
                self.assertEqual(entries[0].value, 10**60 + 12)

    async def asyncSetUp(self):
        self.enterContext(patch('services.treasure_service.MapService.draw', return_value='normal'))
        self.catalog = install_test_catalog(self)
        with patch.dict(os.environ, {"MYSQL_URL": os.environ["TAKARA_TEST_MYSQL_URL"]}):
            config = DatabaseConfig.from_env()
        await DbService.connect(config)
        self.addAsyncCleanup(DbService.close)
        # 既存DBを破壊しない。テスト用の空DBだけを受け付ける。
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SHOW TABLES")
            if await cursor.fetchall():
                self.fail(
                    "MySQL結合テストには空の専用DBを指定してください。既存テーブルは削除しません。"
                )
        self.addAsyncCleanup(self.remove_created_tables)
        # テスト用DBにだけ、手動実行と同じSQLでテーブルを用意する。
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for statement in TABLES_SQL.split(";"):
                if statement.strip():
                    await cursor.execute(statement)
        self.enterContext(patch.object(SettingsService, "_lock", asyncio.Lock()))
        self.enterContext(
            patch("services.treasure_service.random.randint", return_value=1)
        )

    async def remove_created_tables(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            for table in (
                "admin_logs",
                "active_explorations",
                "unlock_notifications",
                "user_progress_events",
                "user_progress",
                "statistics",
                "settings",
            ):
                await cursor.execute(f"DROP TABLE IF EXISTS {table}")

    async def test_game_save_statistics_and_test_cleanup(self):
        await SettingsService.update(
            {"beginner_price": 1234}, 1545489116127559681, "管理者🌟", "価格変更"
        )
        self.assertEqual((await SettingsService.get_all())["beginner_price"], 1234)
        session = await TreasureService.create(
            1545489116127559682, "参加者🌟", "beginner"
        )
        await TreasureService.explore(session)
        await TreasureService.retreat(session)
        await TreasureService.save_result(session)
        await TreasureService.release_user(session.user_id, session.id)
        rows = await AdminService.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], 1545489116127559682)
        self.assertEqual(rows[0]["user_name"], "参加者🌟")
        self.assertEqual(rows[0]["start_price"], 1234)
        self.assertEqual(rows[0]["final_reward"], 700)
        await SettingsService.update(
            {"test_mode": "always_fail"}, 1, "admin", "テスト変更"
        )
        # テストモードは解放進捗を増やさないが、未解放難易度の開始制限は有効。
        test_session = await TreasureService.create(2, "test", "beginner")
        await TreasureService.explore(test_session)
        summary = await AdminService.statistics()
        self.assertEqual(
            (summary["total"], summary["consumed"], summary["payout"]), (1, 1234, 700)
        )
        self.assertEqual(await AdminService.delete_test(1, "admin"), 1)
        self.assertEqual(len(await AdminService.history()), 1)
        self.assertEqual(len(await AdminService.admin_logs()), 3)

    async def test_difficulty_unlock_is_based_on_current_exploration_count(self):
        user_id = 1545489116127559683
        await SettingsService.update(
            {"intermediate_unlock": 1}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "unlock-test", "beginner")
        await TreasureService.explore(session)
        await TreasureService.retreat(session)
        await TreasureService.release_user(session.user_id, session.id)

        # 初級探索1回・条件1回なら中級に挑戦できる。
        unlocked = await TreasureService.create(user_id, "unlock-test", "intermediate")
        self.assertEqual(unlocked.difficulty, "intermediate")
        await TreasureService.retreat(unlocked)
        await TreasureService.release_user(unlocked.user_id, unlocked.id)

        # 条件を2回へ引き上げると、探索回数1回では再び未達になる。
        await SettingsService.update(
            {"intermediate_unlock": 2}, 1, "admin", "解放条件変更"
        )
        with self.assertRaises(ValueError):
            await TreasureService.create(user_id, "unlock-test", "intermediate")

        # 初級をもう1回探索して合計2回になれば、再び中級に挑戦できる。
        session = await TreasureService.create(user_id, "unlock-test", "beginner")
        await TreasureService.explore(session)
        await TreasureService.retreat(session)
        await TreasureService.release_user(session.user_id, session.id)
        unlocked = await TreasureService.create(user_id, "unlock-test", "intermediate")
        self.assertEqual(unlocked.difficulty, "intermediate")

    async def test_database_claim_blocks_same_user_across_service_calls(self):
        user_id = 1545489116127559691
        first = await TreasureService.create(user_id, "claim-test", "beginner")
        with self.assertRaises(Exception) as caught:
            await TreasureService.create(user_id, "claim-test", "beginner")
        self.assertIn("進行中", str(caught.exception))
        await TreasureService.release_user(first.user_id, first.id)
        second = await TreasureService.create(user_id, "claim-test", "beginner")
        self.assertNotEqual(first.id, second.id)
        await TreasureService.release_user(second.user_id, second.id)

    async def test_progress_save_retry_does_not_double_count_or_skip_reward(self):
        user_id = 1545489116127559684
        await SettingsService.update({"beginner_max": 3}, 1, "admin", "最大探索変更")
        session = await TreasureService.create(user_id, "retry-test", "beginner")
        original_record = ProgressService.record_exploration
        calls = 0

        async def lose_response_after_commit(*args, **kwargs):
            nonlocal calls
            result = await original_record(*args, **kwargs)
            calls += 1
            if calls == 1:
                # DBのCOMMITは成功したが、Botが成功応答を受け取れなかった状況。
                raise RuntimeError("commit成功後に通信断")
            return result

        with patch.object(
            ProgressService,
            "record_exploration",
            side_effect=lose_response_after_commit,
        ):
            with self.assertRaises(RuntimeError):
                await TreasureService.explore(session)
            self.assertEqual(session.exploration_count, 1)

            # 同じ探索IDを再送しても、永続化した冪等性キーにより二重加算しない。
            await TreasureService.explore(session)
            await TreasureService.explore(session)
            await TreasureService.explore(session)

        self.assertEqual(session.exploration_count, 3)
        self.assertEqual(session.success_count, 3)
        self.assertEqual(session.reward, 2100)
        self.assertEqual(len(session.found_treasures), 3)
        self.assertEqual(session.result, "max_success")
        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 3)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT COUNT(*) AS count FROM user_progress_events WHERE user_id = %s",
                (user_id,),
            )
            self.assertEqual((await cursor.fetchone())["count"], 3)

    async def expire_claim(self, user_id):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "UPDATE active_explorations SET expires_at = DATE_SUB(NOW(), INTERVAL 1 SECOND) WHERE user_id = %s",
                (user_id,),
            )

    async def test_concurrent_claims_have_exactly_one_owner(self):
        results = await asyncio.gather(
            *(TreasureService.create(123, "race", "beginner") for _ in range(4)),
            return_exceptions=True,
        )
        self.assertEqual(
            sum(isinstance(result, TreasureAlreadyActive) for result in results), 3
        )
        self.assertEqual(
            sum(not isinstance(result, Exception) for result in results), 1
        )

    async def test_expired_claim_cannot_be_revived_or_replace_new_owner(self):
        session = await TreasureService.create(123, "old", "beginner")
        await self.expire_claim(session.user_id)
        with self.assertRaises(TreasureSessionExpired):
            await TreasureService.explore(session)
        newer = await TreasureService.create(123, "new", "beginner")
        for operation in (TreasureService.explore, TreasureService.retreat):
            with self.assertRaises(TreasureSessionExpired):
                await operation(session)
        self.assertEqual(session.exploration_count, 0)
        self.assertIsNone(session.result)
        await TreasureService.release_user(session.user_id, session.id)
        # 旧セッションの終了処理が、新しい所有者の開始枠を削除しない。
        with self.assertRaises(TreasureAlreadyActive):
            await TreasureService.create(123, "third", "beginner")
        await TreasureService.explore(newer)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            1,
        )

    async def test_repeated_refresh_in_same_second_is_valid(self):
        session = await TreasureService.create(123, "refresh", "beginner")
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SET timestamp = UNIX_TIMESTAMP()")
            try:
                await ActiveExplorationRepository.refresh(cursor, 123, session.id)
                await ActiveExplorationRepository.refresh(cursor, 123, session.id)
            finally:
                await cursor.execute("SET timestamp = 0")

    async def test_lost_ownership_between_roll_and_save_blocks_progress(self):
        session = await TreasureService.create(123, "old", "beginner")
        original_record = ProgressService.record_exploration

        async def replace_owner(*args, **kwargs):
            await self.expire_claim(123)
            await TreasureService.create(123, "new", "beginner")
            return await original_record(*args, **kwargs)

        with patch.object(
            ProgressService, "record_exploration", side_effect=replace_owner
        ):
            with self.assertRaises(TreasureSessionExpired):
                await TreasureService.explore(session)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            0,
        )
        self.assertEqual(len(await AdminService.history()), 0)

    async def test_lost_ownership_before_result_save_blocks_statistics(self):
        session = await TreasureService.create(123, "old", "beginner")
        await TreasureService.explore(session)
        original_save = TreasureService.save_result

        async def replace_owner(session):
            await self.expire_claim(123)
            await TreasureService.create(123, "new", "beginner")
            return await original_save(session)

        with patch.object(TreasureService, "save_result", side_effect=replace_owner):
            with self.assertRaises(TreasureSessionExpired):
                await TreasureService.retreat(session)
        self.assertEqual(len(await AdminService.history()), 0)

    async def test_failed_progress_then_retreat_commits_matching_statistics(self):
        session = await TreasureService.create(123, "retry", "beginner")
        original_increment = ProgressRepository.increment_explorations

        async def fail_after_increment(*args):
            await original_increment(*args)
            raise RuntimeError("connection failed before commit")

        with patch.object(
            ProgressRepository,
            "increment_explorations",
            side_effect=fail_after_increment,
        ):
            with self.assertRaises(RuntimeError):
                await TreasureService.explore(session)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            0,
        )
        await TreasureService.retreat(session)
        await TreasureService.retreat(session)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            1,
        )
        rows = await AdminService.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]["result"], rows[0]["success_count"], rows[0]["final_reward"]),
            ("retreat", 1, 700),
        )

    async def test_commit_ack_loss_then_retreat_does_not_double_count(self):
        session = await TreasureService.create(123, "commit-retry", "beginner")
        original_commit = Connection.commit

        async def lose_ack(connection):
            await original_commit(connection)
            raise OperationalError(2013, "COMMIT response lost")

        with patch.object(Connection, "commit", new=lose_ack):
            with self.assertRaises(OperationalError):
                await TreasureService.explore(session)
        self.assertIsNotNone(session.pending_exploration_id)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            1,
        )
        await TreasureService.retreat(session)
        self.assertEqual(
            (await ProgressService.get_exploration_counts(123))[
                "beginner_explorations"
            ],
            1,
        )
        rows = await AdminService.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["success_count"], rows[0]["final_reward"]), (1, 700))
        self.assertEqual(len(session.found_treasures), 1)

    async def test_owner_row_stays_locked_during_progress_and_result_writes(self):
        session = await TreasureService.create(123, "transaction", "beginner")

        async def assert_owner_locked():
            async with DbService.get_connection() as connection:
                await connection.begin()
                try:
                    async with connection.cursor() as cursor:
                        with self.assertRaises(OperationalError) as caught:
                            await cursor.execute(
                                "SELECT * FROM active_explorations WHERE user_id = 123 FOR UPDATE NOWAIT"
                            )
                        self.assertEqual(caught.exception.args[0], 3572)
                finally:
                    await connection.rollback()

        original_increment = ProgressRepository.increment_explorations
        original_result = (
            ResultRepository.insert_statistics_record_if_session_id_not_exists
        )

        async def increment(*args):
            await assert_owner_locked()
            return await original_increment(*args)

        async def insert_result(*args):
            await assert_owner_locked()
            return await original_result(*args)

        with patch.object(
            ProgressRepository, "increment_explorations", side_effect=increment
        ):
            await TreasureService.explore(session)
        with patch.object(
            ResultRepository,
            "insert_statistics_record_if_session_id_not_exists",
            side_effect=insert_result,
        ):
            await TreasureService.retreat(session)

    async def test_unlock_notification_is_marked_only_after_display_ack(self):
        user_id = 1545489116127559690
        await SettingsService.update(
            {"intermediate_unlock": 1}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "notice-test", "beginner")
        await TreasureService.explore(session)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertFalse(
                await ProgressRepository.has_unlock_notification(
                    cursor, user_id, "intermediate"
                )
            )

        await ProgressService.mark_unlock_notification(user_id, "intermediate")
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertTrue(
                await ProgressRepository.has_unlock_notification(
                    cursor, user_id, "intermediate"
                )
            )

    async def test_unlock_notification_uses_current_settings(self):
        user_id = 1545489116127559685
        await SettingsService.update(
            {"intermediate_unlock": 1}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "settings-test", "beginner")

        # 開始後に条件が1回→2回へ変わった場合、1回目では通知しない。
        await SettingsService.update(
            {"intermediate_unlock": 2}, 1, "admin", "解放条件変更"
        )
        await TreasureService.explore(session)
        self.assertIsNone(session.unlocked_difficulty)
        await TreasureService.retreat(session)
        await TreasureService.release_user(session.user_id, session.id)

        # 現在条件の2回目に到達した時点で通知対象になる。
        session = await TreasureService.create(user_id, "settings-test", "beginner")
        await TreasureService.explore(session)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

    async def test_final_result_failure_rolls_back_progress_with_statistics(self):
        user_id = 1545489116127559686
        await SettingsService.update({"beginner_max": 1}, 1, "admin", "最大探索変更")
        session = await TreasureService.create(user_id, "atomic-test", "beginner")
        with patch(
            "services.progress_service.ResultRepository.insert_statistics_record_if_session_id_not_exists",
            side_effect=RuntimeError("statistics save failed"),
        ):
            with self.assertRaises(RuntimeError):
                await TreasureService.explore(session)

        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 0)
        self.assertEqual(len(await AdminService.history()), 0)

        await TreasureService.explore(session)
        progress = await ProgressService.get_exploration_counts(user_id)
        self.assertEqual(progress["beginner_explorations"], 1)
        self.assertEqual(len(await AdminService.history()), 1)

    async def test_lowered_threshold_can_issue_unlock_notification(self):
        user_id = 1545489116127559687
        await SettingsService.update(
            {"intermediate_unlock": 20}, 1, "admin", "解放条件変更"
        )
        for _ in range(3):
            session = await TreasureService.create(user_id, "lower-test", "beginner")
            for _ in range(5):
                await TreasureService.explore(session)
            await TreasureService.release_user(session.user_id, session.id)

        await SettingsService.update(
            {"intermediate_unlock": 10}, 1, "admin", "解放条件変更"
        )
        session = await TreasureService.create(user_id, "lower-test", "beginner")
        await TreasureService.explore(session)
        self.assertEqual(session.unlocked_difficulty, "intermediate")

    async def test_test_mode_does_not_increment_unlock_progress(self):
        await SettingsService.update(
            {"test_mode": "always_success", "intermediate_unlock": 1},
            1,
            "admin",
            "テスト変更",
        )
        session = await TreasureService.create(999, "test", "beginner")
        await TreasureService.explore(session)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT beginner_explorations FROM user_progress WHERE user_id = %s",
                (999,),
            )
            self.assertIsNone(await cursor.fetchone())

    async def test_setting_and_log_rollback_together(self):
        with self.assertRaises(IntegrityError):
            await SettingsService.update({"beginner_price": 99}, None, "admin", "test")
        self.assertEqual((await SettingsService.get_all())["beginner_price"], 1000)
        self.assertEqual(await AdminService.admin_logs(), ())

    async def test_empty_settings_use_defaults_without_inserting_rows(self):
        self.assertEqual(await SettingsService.get_all(), DEFAULT_SETTINGS)
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT COUNT(*) AS count FROM settings")
            self.assertEqual((await cursor.fetchone())["count"], 0)

    async def test_test_history_deletion_rolls_back_when_log_fails(self):
        await SettingsService.update({"test_mode": "always_fail"}, 1, "admin", "test")
        session = await TreasureService.create(2, "test", "beginner")
        await TreasureService.explore(session)
        with self.assertRaises(IntegrityError):
            await AdminService.delete_test(None, "admin")
        self.assertEqual(len(await AdminService.history()), 1)
        self.assertEqual(len(await AdminService.admin_logs()), 1)

    async def test_operation_toggle_is_saved_with_log(self):
        self.assertEqual(await SettingsService.toggle_operation(1, "admin"), 0)
        self.assertEqual(await SettingsService.toggle_operation(1, "admin"), 1)
        self.assertEqual((await SettingsService.get_all())["operation"], 1)
        self.assertEqual(len(await AdminService.admin_logs()), 2)

    async def test_concurrent_toggles_share_lock_and_preserve_all_changes(self):
        states = await asyncio.gather(
            *(SettingsService.toggle_operation(1, "admin") for _ in range(8))
        )
        self.assertEqual(states, [0, 1] * 4)
        self.assertEqual((await SettingsService.get_all())["operation"], 1)
        self.assertEqual(len(await AdminService.admin_logs()), 8)

    async def test_schema_validation_rejects_old_database_before_gameplay(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("DROP TABLE unlock_notifications")
            await cursor.execute("DROP TABLE user_progress_events")
            await cursor.execute("DROP TABLE user_progress")

        with self.assertRaisesRegex(RuntimeError, "不足テーブル"):
            await SchemaService.validate_required_tables()

    async def test_schema_validation_rejects_missing_idempotency_primary_key(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("ALTER TABLE user_progress_events DROP PRIMARY KEY")

        with self.assertRaisesRegex(RuntimeError, "PRIMARY KEY"):
            await SchemaService.validate_required_tables()

    async def test_schema_validation_accepts_declared_schema(self):
        await SchemaService.validate_required_tables()

    async def test_schema_validation_rejects_broken_column_definitions(self):
        cases = (
            (
                "user_progress",
                "beginner_explorations",
                "INT UNSIGNED NULL DEFAULT 0",
                "INT UNSIGNED NOT NULL DEFAULT 0",
                "NULL",
            ),
            (
                "user_progress",
                "intermediate_explorations",
                "INT NOT NULL DEFAULT 0",
                "INT UNSIGNED NOT NULL DEFAULT 0",
                "型",
            ),
            (
                "user_progress",
                "beginner_explorations",
                "INT UNSIGNED NOT NULL DEFAULT 1",
                "INT UNSIGNED NOT NULL DEFAULT 0",
                "DEFAULT",
            ),
            (
                "user_progress_events",
                "exploration_id",
                "VARCHAR(36) NOT NULL",
                "VARCHAR(80) NOT NULL",
                "型",
            ),
            (
                "user_progress_events",
                "created_at",
                "DATETIME NOT NULL",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "DEFAULT",
            ),
            (
                "active_explorations",
                "expires_at",
                "DATETIME NULL",
                "DATETIME NOT NULL",
                "NULL",
            ),
            ("statistics", "session_id", "CHAR(36) NULL", "CHAR(36) NOT NULL", "NULL"),
            (
                "statistics",
                "final_reward",
                "DECIMAL(20,0) NOT NULL",
                "DECIMAL(65,0) NOT NULL",
                "型",
            ),
            (
                "statistics",
                "id",
                "BIGINT UNSIGNED NOT NULL",
                "BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
                "AUTO_INCREMENT",
            ),
        )
        for table, column, broken, correct, message in cases:
            with self.subTest(table=table, column=column, broken=broken):
                async with (
                    DbService.get_connection() as connection,
                    connection.cursor() as cursor,
                ):
                    await cursor.execute(
                        f"ALTER TABLE {table} MODIFY {column} {broken}"
                    )
                try:
                    with self.assertRaisesRegex(RuntimeError, message):
                        await SchemaService.validate_required_tables()
                finally:
                    async with (
                        DbService.get_connection() as connection,
                        connection.cursor() as cursor,
                    ):
                        await cursor.execute(
                            f"ALTER TABLE {table} MODIFY {column} {correct}"
                        )

    async def test_schema_validation_rejects_nonunique_composite_and_prefix_session_keys(
        self,
    ):
        for table in ("statistics", "active_explorations"):
            for index in (
                "INDEX session_id (session_id)",
                "UNIQUE session_id (session_id, user_id)",
                "UNIQUE session_id (session_id(8))",
            ):
                with self.subTest(table=table, index=index):
                    async with (
                        DbService.get_connection() as connection,
                        connection.cursor() as cursor,
                    ):
                        await cursor.execute(
                            f"ALTER TABLE {table} DROP INDEX session_id, ADD {index}"
                        )
                    try:
                        with self.assertRaisesRegex(RuntimeError, "UNIQUE"):
                            await SchemaService.validate_required_tables()
                    finally:
                        async with (
                            DbService.get_connection() as connection,
                            connection.cursor() as cursor,
                        ):
                            await cursor.execute(
                                f"ALTER TABLE {table} DROP INDEX session_id, ADD UNIQUE session_id (session_id)"
                            )

    async def test_schema_validation_rejects_nontransactional_engine(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("ALTER TABLE statistics ENGINE=MyISAM")
        with self.assertRaisesRegex(RuntimeError, "InnoDB"):
            await SchemaService.validate_required_tables()

    async def test_schema_validation_rejects_missing_statistics_column(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("ALTER TABLE statistics DROP COLUMN final_reward")
        with self.assertRaisesRegex(RuntimeError, "不足列"):
            await SchemaService.validate_required_tables()

    async def test_read_connection_uses_autocommit_without_transaction(self):
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            self.assertTrue(connection.get_autocommit())
            rows = await SettingsRepository.get_all_settings(cursor)
            self.assertEqual(len(rows), 0)
            self.assertFalse(connection.get_transaction_status())
