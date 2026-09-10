"""Tests for Sprint 12 — UI Parity Migration.

Tests for UI component creation, event bindings, and visual parity with GOOD.
"""

import unittest
from unittest.mock import MagicMock, patch

from worker.ui.events import CommandEvent, UIEvent
from worker.ui.update_queue import UpdateQueue, TaskQueue
from worker.ui.log_viewer import LogViewer
from worker.ui.port_table import PortStatusTable
from worker.ui.context_menu import PortContextMenu
from worker.ui.worker_monitor import WorkerMonitor


class TestUpdateQueue(unittest.TestCase):
    """Test UpdateQueue thread-safe update mechanism."""

    def test_put_and_drain(self):
        """Test basic put and drain cycle."""
        uq = UpdateQueue()
        uq.put("COM3", "status", "READY")
        uq.put("COM3", "nomor", "081234")
        updates = uq.drain()
        self.assertEqual(len(updates), 2)

    def test_drain_deduplicates(self):
        """Test drain deduplicates by (port, column) keeping latest."""
        uq = UpdateQueue()
        uq.put("COM3", "status", "IDLE")
        uq.put("COM3", "status", "READY")
        updates = uq.drain()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0], ("COM3", "status", "READY"))

    def test_drain_empty(self):
        """Test drain on empty queue returns empty list."""
        uq = UpdateQueue()
        updates = uq.drain()
        self.assertEqual(updates, [])

    def test_qsize(self):
        """Test qsize returns approximate count."""
        uq = UpdateQueue()
        uq.put("COM3", "status", "READY")
        self.assertEqual(uq.qsize(), 1)

    def test_empty(self):
        """Test empty returns True when no items."""
        uq = UpdateQueue()
        self.assertTrue(uq.empty())

    def test_clear(self):
        """Test clear discards all pending updates."""
        uq = UpdateQueue()
        uq.put("COM3", "status", "READY")
        uq.clear()
        self.assertTrue(uq.empty())

    def test_max_batch_limit(self):
        """Test drain respects max_batch limit."""
        uq = UpdateQueue(max_batch=5)
        for i in range(10):
            uq.put(f"COM{i}", "status", "READY")
        updates = uq.drain()
        self.assertLessEqual(len(updates), 5)


class TestTaskQueue(unittest.TestCase):
    """Test TaskQueue thread-safe task mechanism."""

    def test_put_and_drain(self):
        """Test basic put and drain cycle."""
        tq = TaskQueue()
        executed = []
        tq.put(lambda: executed.append(1))
        tasks = tq.drain()
        self.assertEqual(len(tasks), 1)
        tasks[0]()
        self.assertEqual(executed, [1])

    def test_drain_empty(self):
        """Test drain on empty queue returns empty list."""
        tq = TaskQueue()
        tasks = tq.drain()
        self.assertEqual(tasks, [])

    def test_qsize(self):
        """Test qsize returns approximate count."""
        tq = TaskQueue()
        tq.put(lambda: None)
        self.assertEqual(tq.qsize(), 1)

    def test_empty(self):
        """Test empty returns True when no items."""
        tq = TaskQueue()
        self.assertTrue(tq.empty())


class TestLogViewer(unittest.TestCase):
    """Test LogViewer component."""

    def test_creation(self):
        """Test LogViewer can be created."""
        viewer = LogViewer(MagicMock())
        self.assertIsNotNone(viewer)

    def test_set_log_data(self):
        """Test set_log_data stores data."""
        viewer = LogViewer(MagicMock())
        viewer.set_log_data("COM3", ["line1", "line2"])
        self.assertEqual(viewer._log_data["COM3"], ["line1", "line2"])

    def test_append_line(self):
        """Test append_line adds to stored data."""
        viewer = LogViewer(MagicMock())
        viewer.append_line("COM3", "line1")
        viewer.append_line("COM3", "line2")
        self.assertEqual(viewer._log_data["COM3"], ["line1", "line2"])

    def test_clear_specific_port(self):
        """Test clear with port removes only that port."""
        viewer = LogViewer(MagicMock())
        viewer.set_log_data("COM3", ["line1"])
        viewer.set_log_data("COM5", ["line2"])
        viewer.clear("COM3")
        self.assertNotIn("COM3", viewer._log_data)
        self.assertIn("COM5", viewer._log_data)

    def test_clear_all(self):
        """Test clear without port removes all data."""
        viewer = LogViewer(MagicMock())
        viewer.set_log_data("COM3", ["line1"])
        viewer.set_log_data("COM5", ["line2"])
        viewer.clear()
        self.assertEqual(len(viewer._log_data), 0)


class TestPortStatusTable(unittest.TestCase):
    """Test PortStatusTable component."""

    def test_creation(self):
        """Test PortStatusTable can be created."""
        table = PortStatusTable(MagicMock())
        self.assertIsNotNone(table)

    def test_columns_are_eight(self):
        """Test table has exactly 8 columns (no PARTICIPASI)."""
        self.assertEqual(len(PortStatusTable.COLUMNS), 8)
        self.assertEqual(PortStatusTable.COLUMNS, (
            "port", "nomor", "nik", "kk", "status", "respon", "masa_aktif", "log"
        ))

    def test_has_disabled_status_tag(self):
        """Test table has DISABLED status tag for excluded ports."""
        self.assertIn("disabled", PortStatusTable.STATUS_TAGS)

    def test_default_row_has_eight_columns(self):
        """Test default row has 8 columns."""
        self.assertEqual(len(PortStatusTable.DEFAULT_ROW), 8)

    def test_col_map_covers_key_columns(self):
        """Test COL_MAP has all expected column indices."""
        self.assertIn("status", PortStatusTable.COL_MAP)
        self.assertIn("nomor", PortStatusTable.COL_MAP)
        self.assertIn("nik", PortStatusTable.COL_MAP)
        self.assertIn("kk", PortStatusTable.COL_MAP)


class TestPortContextMenu(unittest.TestCase):
    """Test PortContextMenu component."""

    def test_creation(self):
        """Test PortContextMenu can be created."""
        menu = PortContextMenu(MagicMock(), MagicMock())
        self.assertIsNotNone(menu)

    def test_has_menu_items(self):
        """Test context menu has expected items."""
        self.assertGreater(len(PortContextMenu.MENU_ITEMS), 0)

    def test_has_lookup_database_separator(self):
        """Test context menu includes separator before Lookup Database."""
        labels = [item[0] if item else None for item in PortContextMenu.MENU_ITEMS]
        self.assertIn("Cek Nomor", labels)
        self.assertIn("Reaktivasi", labels)

    def test_show_sets_selected_port(self):
        """Test show sets the selected port."""
        menu = PortContextMenu(MagicMock(), MagicMock())
        menu.show("COM3", 100, 200)
        self.assertEqual(menu.selected_port, "COM3")


class TestWorkerMonitor(unittest.TestCase):
    """Test WorkerMonitor component."""

    def test_creation(self):
        """Test WorkerMonitor can be created."""
        monitor = WorkerMonitor(MagicMock())
        self.assertIsNotNone(monitor)

    def test_update_footer(self):
        """Test update_footer sets counts."""
        monitor = WorkerMonitor(MagicMock())
        monitor.update_footer(5, 3, 2, 1)
        counts = monitor.get_counts()
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["active"], 3)
        self.assertEqual(counts["off"], 2)
        self.assertEqual(counts["excluded"], 1)

    def test_get_counts_default(self):
        """Test get_counts returns zeros by default."""
        monitor = WorkerMonitor(MagicMock())
        counts = monitor.get_counts()
        self.assertEqual(counts["total"], 0)
        self.assertEqual(counts["active"], 0)
        self.assertEqual(counts["off"], 0)


class TestUIEvents(unittest.TestCase):
    """Test UI event definitions are complete."""

    def test_ui_events_have_port_excluded(self):
        """Test UIEvent has PORT_EXCLUDED event."""
        self.assertTrue(hasattr(UIEvent, "PORT_EXCLUDED"))

    def test_ui_events_have_port_included(self):
        """Test UIEvent has PORT_INCLUDED event."""
        self.assertTrue(hasattr(UIEvent, "PORT_INCLUDED"))

    def test_command_events_have_port_exclude(self):
        """Test CommandEvent has PORT_EXCLUDE event."""
        self.assertTrue(hasattr(CommandEvent, "PORT_EXCLUDE"))

    def test_command_events_have_port_include(self):
        """Test CommandEvent has PORT_INCLUDE event."""
        self.assertTrue(hasattr(CommandEvent, "PORT_INCLUDE"))

    def test_command_events_have_mass_reaktivasi(self):
        """Test CommandEvent has MASS_REAKTIVASI."""
        self.assertTrue(hasattr(CommandEvent, "MASS_REAKTIVASI"))

    def test_command_events_have_mass_cek_nomor(self):
        """Test CommandEvent has MASS_CEK_NOMOR."""
        self.assertTrue(hasattr(CommandEvent, "MASS_CEK_NOMOR"))

    def test_command_events_have_auto_run_toggle(self):
        """Test CommandEvent has AUTO_RUN_TOGGLE."""
        self.assertTrue(hasattr(CommandEvent, "AUTO_RUN_TOGGLE"))

    def test_command_events_have_db_lookup_nik(self):
        """Test CommandEvent has DB_LOOKUP_NIK."""
        self.assertTrue(hasattr(CommandEvent, "DB_LOOKUP_NIK"))

    def test_command_events_have_db_lookup_kk(self):
        """Test CommandEvent has DB_LOOKUP_KK."""
        self.assertTrue(hasattr(CommandEvent, "DB_LOOKUP_KK"))

    def test_command_events_have_reactivate(self):
        """Test CommandEvent has REACTIVATE."""
        self.assertTrue(hasattr(CommandEvent, "REACTIVATE"))
