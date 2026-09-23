import unittest
from unittest.mock import AsyncMock, patch

from tests.test_views import interaction
from views.history import HistoryView, history_embed


def record(i):
    return dict(id=i, user_id=1, user_name='*' * 255, is_test=False,
                difficulty='上級', start_price=10**65 - 1, final_reward=10**65 - 1,
                success_count=215, result='max_success', created_at='2026-09-23 12:00:00')


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_search_pagination_switch_and_clear(self):
        view = HistoryView(1, [record(100)], False)
        event = interaction(admin=True)
        with patch('views.history.AdminService.history_page', new_callable=AsyncMock,
                   side_effect=[([record(30)], True), ([record(20)], False), ([], False), ([record(100)], False)]) as fetch:
            await view.filter_user(event, 7)
            fetch.assert_awaited_with(user_id=7)
            await view.turn_page(event, 1)
            fetch.assert_awaited_with(30, user_id=7)
            await view.filter_user(event, 8)
            self.assertEqual(view.page, 0)
            self.assertEqual(len(view.pages), 1)
            self.assertEqual(view.target_user_id, 8)
            self.assertTrue(view.next.disabled)
            self.assertIn('ID: 8', event.edit_original_response.call_args.kwargs['embed'].description)
            await view.filter_user(event, None)
            self.assertIsNone(view.target_user_id)
            self.assertEqual(view.pages[0][0][0]['id'], 100)

    async def test_failed_user_search_keeps_previous_filter_and_page(self):
        view = HistoryView(1, [record(100)], False)
        event = interaction(admin=True)
        event.edit_original_response.side_effect = RuntimeError('offline')
        with patch('views.history.AdminService.history_page', new_callable=AsyncMock, return_value=([record(1)], False)):
            with self.assertRaises(RuntimeError):
                await view.filter_user(event, 7)
        self.assertIsNone(view.target_user_id)
        self.assertEqual(view.pages[0][0][0]['id'], 100)

    async def test_next_previous_and_final_page(self):
        view = HistoryView(1, [record(i) for i in range(21, 11, -1)], True)
        event = interaction(admin=True)
        with patch('views.history.AdminService.history_page', new_callable=AsyncMock,
                   side_effect=[([record(i) for i in range(11, 1, -1)], True), ([record(1)], False)]) as fetch:
            self.assertTrue(view.previous.disabled)
            await view.turn_page(event, 1)
            fetch.assert_awaited_with(12)
            await view.turn_page(event, -1)
            await view.turn_page(event, 1)
            self.assertEqual(fetch.await_count, 1)
            await view.turn_page(event, 1)
            self.assertEqual(view.page, 2)
            self.assertTrue(view.next.disabled)
            await view.turn_page(event, 1)
            self.assertEqual(fetch.await_count, 2)

    async def test_send_failure_can_retry_same_page(self):
        view = HistoryView(1, [record(20)], True)
        event = interaction(admin=True)
        event.edit_original_response.side_effect = [RuntimeError('offline'), None]
        with patch('views.history.AdminService.history_page', new_callable=AsyncMock,
                   return_value=([record(19)], False)) as fetch:
            with self.assertRaises(RuntimeError):
                await view.turn_page(event, 1)
            self.assertEqual(view.page, 0)
            await view.turn_page(event, 1)
            self.assertEqual(view.page, 1)
            self.assertEqual(fetch.await_count, 1)

    async def test_deleted_next_page_and_permission_checks(self):
        view = HistoryView(1, [record(20)], True)
        self.assertFalse(await view.interaction_check(interaction()))
        other = interaction(admin=True)
        other.user.id = 2
        self.assertFalse(await view.interaction_check(other))
        self.assertTrue(await view.interaction_check(interaction(admin=True)))
        with patch('views.history.AdminService.history_page', new_callable=AsyncMock, return_value=([], False)):
            await view.turn_page(interaction(admin=True), 1)
        self.assertEqual(view.page, 0)
        self.assertTrue(view.next.disabled)

    def test_ten_large_records_fit_one_message(self):
        embed = history_embed([record(i) for i in range(10)], 0)
        self.assertEqual(len(embed.fields), 10)
        self.assertLessEqual(len(embed), 6000)
        self.assertTrue(all(len(f.name) <= 256 and len(f.value) <= 1024 for f in embed.fields))
        self.assertIn('まだ履歴', history_embed([], 0).description)
