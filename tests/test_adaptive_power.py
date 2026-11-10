"""Тести адаптивних розмірів чату й політики вивантаження моделі.

Обидва модулі навмисно не тягнуть tkinter:
:mod:`blackchpok_ide.adaptive` рахує числа з розмірів екрана,
:mod:`blackchpok_ide.power` вирішує, коли віддати пам'ять відеокарти.

Запуск: python -m unittest tests.test_adaptive_power -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import adaptive, power  # noqa: E402


class TestChatWidth(unittest.TestCase):
    """Ширина колонки діалогу під різні екрани."""

    def test_narrow_screen_gets_narrower_chat(self) -> None:
        narrow = adaptive.chat_width_for(1366, sidebar=264)
        wide = adaptive.chat_width_for(2560, sidebar=264)
        self.assertLess(narrow, wide, f"{narrow} vs {wide}")

    def test_never_below_minimum(self) -> None:
        self.assertGreaterEqual(adaptive.chat_width_for(800, sidebar=264),
                                adaptive.MIN_CHAT_WIDTH)

    def test_never_above_maximum(self) -> None:
        self.assertLessEqual(adaptive.chat_width_for(5120, sidebar=264),
                             adaptive.MAX_CHAT_WIDTH)

    def test_leaves_room_for_editor(self) -> None:
        """Чат не має з'їдати вузький екран: лишається місце редактору."""
        for screen in (1280, 1366, 1440, 1920, 2560, 3840):
            width = adaptive.chat_width_for(screen, sidebar=264)
            self.assertLess(width, screen, screen)
            self.assertGreater(screen - 264 - width, 300,
                               f"на {screen}px редактору лишилось "
                               f"{screen - 264 - width}px")

    def test_explicit_limits_win(self) -> None:
        width = adaptive.chat_width_for(1920, sidebar=264, min_width=900, max_width=1000)
        self.assertGreaterEqual(width, 900)
        self.assertLessEqual(width, 1000)

    def test_window_width_is_not_double_reduced(self) -> None:
        """Ширина вікна вже без навігації — її не можна зменшувати вдвічі.

        Регресія: ``sidebar`` віднімався і від екрана, і від вікна, тому на
        вікні 1296 px чат виходив 474 px замість ~600.
        """
        metrics = adaptive.metrics_for(screen=(1920, 1080), window=(1296, 900),
                                       feed_height=600, sidebar=264)
        self.assertGreater(metrics.chat_width, 520, metrics.chat_width)

    def test_wider_window_gives_wider_chat(self) -> None:
        widths = [adaptive.metrics_for(screen=(1920, 1080), window=(win, 900),
                                       feed_height=600, sidebar=264).chat_width
                  for win in (1100, 1400, 1800, 2400)]
        self.assertEqual(widths, sorted(widths), widths)


class TestBodyLines(unittest.TestCase):
    """Скільки рядків показує одна відповідь."""

    def test_small_window_fewer_lines(self) -> None:
        self.assertLess(adaptive.body_lines_for(400), adaptive.body_lines_for(1200))

    def test_respects_bounds(self) -> None:
        for height in (0, 10, 100, 800, 5000):
            lines = adaptive.body_lines_for(height)
            self.assertGreaterEqual(lines, adaptive.MIN_BODY_LINES, height)
            self.assertLessEqual(lines, adaptive.MAX_BODY_LINES, height)

    def test_zero_height_still_readable(self) -> None:
        self.assertGreaterEqual(adaptive.body_lines_for(0), adaptive.MIN_BODY_LINES)


class TestMetrics(unittest.TestCase):
    """Повний зріз розмірів."""

    def test_metrics_are_consistent(self) -> None:
        metrics = adaptive.metrics_for(screen=(1920, 1080), window=(1560, 940),
                                       feed_height=600)
        self.assertGreater(metrics.chat_width, 0)
        self.assertGreater(metrics.body_lines, 0)
        self.assertLessEqual(metrics.composer_width, metrics.chat_width)
        self.assertFalse(metrics.compact)

    def test_medium_window_is_neither_flag(self) -> None:
        """Вікно 1200 px: не вузьке, але й не «просторе»."""
        metrics = adaptive.metrics_for(screen=(1920, 1080), window=(1200, 900))
        self.assertFalse(metrics.compact)
        self.assertFalse(metrics.roomy)

    def test_compact_flag_on_small_window(self) -> None:
        metrics = adaptive.metrics_for(screen=(1366, 768), window=(820, 700))
        self.assertTrue(metrics.compact)

    def test_roomy_flag_on_large_window(self) -> None:
        metrics = adaptive.metrics_for(screen=(2560, 1440), window=(2000, 1200))
        self.assertTrue(metrics.roomy)

    def test_describe_is_readable(self) -> None:
        text = adaptive.metrics_for().describe()
        self.assertIn("px", text)

    def test_screen_size_without_widget(self) -> None:
        self.assertEqual(adaptive.screen_size(None), (1920, 1080))

    def test_sidebar_width_adapts(self) -> None:
        self.assertLess(adaptive.sidebar_width_for(1280), adaptive.sidebar_width_for(2560))

    def test_sidebar_width_keeps_sane_bounds(self) -> None:
        for screen in (0, 800, 1280, 1920, 3840):
            width = adaptive.sidebar_width_for(screen, current=264)
            self.assertGreaterEqual(width, 180)
            self.assertLessEqual(width, 380)


class _FakeServer:
    """Мінімальна підміна :class:`runtime.LocalServer` для тестів."""

    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.stopped = 0

    def stop(self) -> None:
        self.running = False
        self.stopped += 1


class TestIdlePolicy(unittest.TestCase):
    """Політика простою."""

    def test_policy_normalises_threshold(self) -> None:
        policy = power.IdlePolicy(idle_seconds=5).normalise()
        self.assertEqual(policy.idle_seconds, power.MIN_IDLE_SECONDS)
        policy = power.IdlePolicy(idle_seconds=99_999).normalise()
        self.assertEqual(policy.idle_seconds, power.MAX_IDLE_SECONDS)

    def test_recent_activity_blocks_unload(self) -> None:
        tracker = power.IdleTracker(policy=power.IdlePolicy(idle_seconds=300))
        tracker.touch()
        self.assertFalse(tracker.should_unload(busy=False, autonomous=False, loaded=True))

    def test_long_idle_allows_unload(self) -> None:
        tracker = power.IdleTracker(policy=power.IdlePolicy(idle_seconds=60))
        tracker.last_touch -= 600
        self.assertTrue(tracker.should_unload(busy=False, autonomous=False, loaded=True))

    def test_autonomous_mode_never_unloads(self) -> None:
        """В автономному режимі модель потрібна весь час — не вивантажуємо."""
        tracker = power.IdleTracker(policy=power.IdlePolicy(idle_seconds=60))
        tracker.last_touch -= 100_000
        self.assertFalse(tracker.should_unload(busy=False, autonomous=True, loaded=True))

    def test_busy_agent_blocks_unload(self) -> None:
        tracker = power.IdleTracker(policy=power.IdlePolicy(idle_seconds=60))
        tracker.last_touch -= 600
        self.assertFalse(tracker.should_unload(busy=True, autonomous=False, loaded=True))

    def test_disabled_policy_does_nothing(self) -> None:
        tracker = power.IdleTracker(policy=power.IdlePolicy(enabled=False, idle_seconds=60))
        tracker.last_touch -= 10_000
        self.assertFalse(tracker.should_unload(busy=False, autonomous=False, loaded=True))

    def test_unloaded_model_is_not_unloaded_twice(self) -> None:
        tracker = power.IdleTracker(policy=power.IdlePolicy(idle_seconds=60))
        tracker.last_touch -= 600
        self.assertFalse(tracker.should_unload(busy=False, autonomous=False, loaded=False))

    def test_idle_text(self) -> None:
        tracker = power.IdleTracker()
        self.assertIn("с", tracker.idle_text)


class TestModelKeeper(unittest.TestCase):
    """Керування моделлю: вивантаження й повернення."""

    def test_loaded_state(self) -> None:
        server = _FakeServer(True)
        keeper = power.ModelKeeper(server_provider=lambda: server)
        self.assertTrue(keeper.loaded)
        self.assertEqual(keeper.state_text, power.STATE_LOADED)

    def test_unload_stops_server(self) -> None:
        server = _FakeServer(True)
        keeper = power.ModelKeeper(server_provider=lambda: server)
        self.assertTrue(keeper.unload())
        self.assertEqual(server.stopped, 1)
        self.assertFalse(keeper.loaded)

    def test_unload_without_server_is_safe(self) -> None:
        keeper = power.ModelKeeper()
        self.assertFalse(keeper.unload())
        self.assertEqual(keeper.state_text, power.STATE_UNKNOWN)

    def test_broken_provider_is_safe(self) -> None:
        def boom():
            raise RuntimeError("навмисно")

        keeper = power.ModelKeeper(server_provider=boom)
        self.assertFalse(keeper.loaded)

    def test_poll_respects_autonomous_mode(self) -> None:
        server = _FakeServer(True)
        keeper = power.ModelKeeper(server_provider=lambda: server)
        keeper.tracker.policy.idle_seconds = power.MIN_IDLE_SECONDS
        keeper.tracker.last_touch -= 10_000
        self.assertFalse(keeper.poll(busy=False, autonomous=True))
        self.assertEqual(server.stopped, 0)

    def test_poll_unloads_when_idle_and_offline(self) -> None:
        server = _FakeServer(True)
        keeper = power.ModelKeeper(server_provider=lambda: server)
        keeper.tracker.policy.idle_seconds = power.MIN_IDLE_SECONDS
        keeper.tracker.last_touch -= 10_000
        self.assertTrue(keeper.poll(busy=False, autonomous=False))
        self.assertEqual(server.stopped, 1)

    def test_unload_resets_timer(self) -> None:
        server = _FakeServer(True)
        keeper = power.ModelKeeper(server_provider=lambda: server)
        keeper.unload()
        self.assertLess(keeper.tracker.idle_seconds, 5)

    def test_reload_calls_provider(self) -> None:
        called: list[bool] = []
        server = _FakeServer(False)
        keeper = power.ModelKeeper(server_provider=lambda: server,
                                   start_provider=lambda: called.append(True))
        self.assertTrue(keeper.reload())
        self.assertTrue(called)

    def test_reload_without_provider_is_safe(self) -> None:
        keeper = power.ModelKeeper(server_provider=lambda: _FakeServer(False))
        self.assertFalse(keeper.reload())


if __name__ == "__main__":
    unittest.main(verbosity=2)
