"""Tests for Sprint 15R.1 — Workspace Table Order & Idle Display Finalization.

Covers:
1. COM numeric order: COM9, COM10, COM101, COM122.
2. Arbitrary row insertion order is rendered numerically.
3. Parallel update arrival order cannot disturb numeric order.
4. update_cell() inserting a missing row preserves numeric order.
5. Workspace tab rebuild from cache is numerically sorted.
6. Deleting a row preserves numeric order.
7. Applying/removing a filter preserves numeric order among visible rows.
8. Selection and LOG row identity remain valid after reorder.
9. NOT_INSERTED displays IDLE and RESPON '-'.
10. NOT_READY displays IDLE and RESPON '-'.
11. UNKNOWN displays IDLE and RESPON '-'.
12. CHECKING displays IDLE and RESPON '-'.
13. STANDBY displays IDLE and RESPON '-'.
14. READY and workflow-result display behavior remains unchanged.
15. Domain eligibility remains unchanged despite the simplified UI label.
"""

import unittest
from unittest.mock import MagicMock


# ------------------------------------------------------------------
# Helper: create a mock treeview-compatible PortStatusTable
# ------------------------------------------------------------------

def _make_table():
    """Create a PortStatusTable with mocked Tkinter dependencies."""
    from worker.ui.port_table import PortStatusTable
    table = PortStatusTable.__new__(PortStatusTable)
    table._parent = MagicMock()
    table._on_log_click = None
    table._row_cache = {}
    table._selected_port = None
    table._frame = MagicMock()

    # Mock treeview with trackable children
    tree = MagicMock()
    tree.winfo_exists.return_value = True
    # _children tracks order for move() simulation
    table._children = []
    def get_children():
        return list(table._children)
    tree.get_children.side_effect = get_children
    tree.exists.return_value = False
    def tree_insert(parent, index, iid=None, values=None):
        table._children.append(iid)
        return iid
    tree.insert.side_effect = tree_insert
    def tree_move(item, parent, index):
        if item in table._children:
            table._children.remove(item)
        table._children.insert(index, item)
    tree.move.side_effect = tree_move
    table._tree = tree
    table._scrollbar = MagicMock()
    return table


# ------------------------------------------------------------------
# 1. COM numeric order
# ------------------------------------------------------------------

class TestComNumericOrder(unittest.TestCase):
    """Sort utility handles COM9 < COM10 < COM101 < COM122."""

    def test_sort_basic(self):
        from worker.ui.port_table import _com_sort_key
        ports = ["COM10", "COM122", "COM9", "COM101"]
        result = sorted(ports, key=_com_sort_key)
        self.assertEqual(result, ["COM9", "COM10", "COM101", "COM122"])

    def test_sort_high_numbers(self):
        from worker.ui.port_table import _com_sort_key
        ports = ["COM164", "COM101", "COM149", "COM122"]
        result = sorted(ports, key=_com_sort_key)
        self.assertEqual(result, ["COM101", "COM122", "COM149", "COM164"])

    def test_sort_single(self):
        from worker.ui.port_table import _com_sort_key
        self.assertEqual(sorted(["COM5"], key=_com_sort_key), ["COM5"])

    def test_sort_empty(self):
        from worker.ui.port_table import _com_sort_key
        self.assertEqual(sorted([], key=_com_sort_key), [])


# ------------------------------------------------------------------
# 2. Arbitrary insertion order → numeric display
# ------------------------------------------------------------------

class TestArbitraryInsertionOrder(unittest.TestCase):
    """Rows inserted out of order are reordered numerically."""

    def test_insert_out_of_order_reorders(self):
        table = _make_table()
        table.insert_row("COM122", ["COM122", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table.insert_row("COM9", ["COM9", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table.insert_row("COM101", ["COM101", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        # Children should be in numeric order after reorder
        self.assertEqual(table._children, ["COM9", "COM101", "COM122"])

    def test_treeview_children_sorted_after_insert(self):
        table = _make_table()
        table.insert_row("COM200", ["COM200", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table.insert_row("COM1", ["COM1", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table.insert_row("COM100", ["COM100", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        self.assertEqual(table._children, ["COM1", "COM100", "COM200"])


# ------------------------------------------------------------------
# 3. Parallel update arrival order
# ------------------------------------------------------------------

class TestParallelUpdateOrder(unittest.TestCase):
    """Parallel updates arriving in arbitrary order don't disturb numeric order."""

    def test_update_cell_missing_row_inserts_and_reorders(self):
        table = _make_table()
        table.update_cell("COM101", "status", "READY")
        table.update_cell("COM9", "status", "IDLE")
        table.update_cell("COM122", "status", "IDLE")
        # Missing rows inserted + reordered
        self.assertEqual(table._children, ["COM9", "COM101", "COM122"])

    def test_update_existing_row_preserves_order(self):
        table = _make_table()
        # Pre-insert rows
        table.insert_row("COM9", ["COM9", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table.insert_row("COM101", ["COM101", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table._tree.exists.return_value = True
        # Update existing row
        table.update_cell("COM9", "status", "READY")
        # Order unchanged
        self.assertEqual(table._children, ["COM9", "COM101"])


# ------------------------------------------------------------------
# 4. update_cell inserting missing row
# ------------------------------------------------------------------

class TestUpdateCellMissingRow(unittest.TestCase):
    """update_cell() inserting a missing row preserves numeric order."""

    def test_missing_row_inserted_and_reordered(self):
        table = _make_table()
        table.update_cell("COM200", "status", "READY")
        table.update_cell("COM5", "status", "IDLE")
        self.assertEqual(table._children, ["COM5", "COM200"])

    def test_existing_row_updated_no_reorder_needed(self):
        table = _make_table()
        table.insert_row("COM5", ["COM5", "-", "-", "-", "IDLE", "-", "-", "LOG"])
        table._tree.exists.return_value = True
        table.update_cell("COM5", "status", "READY")
        # Only one item, no reorder needed
        self.assertEqual(table._children, ["COM5"])


# ------------------------------------------------------------------
# 5. Workspace tab rebuild from cache
# ------------------------------------------------------------------

class TestWorkspaceTabRebuild(unittest.TestCase):
    """Workspace tab rebuild from _port_data is numerically sorted."""

    def test_restore_from_cache_sorted(self):
        table = _make_table()
        port_states = {
            "COM200": {"port_display": "COM200", "status": "IDLE"},
            "COM9": {"port_display": "COM9", "status": "READY"},
            "COM150": {"port_display": "COM150", "status": "IDLE"},
        }
        table.restore_from_cache(port_states)
        self.assertEqual(table._children, ["COM9", "COM150", "COM200"])

    def test_restore_from_cache_clears_old_rows(self):
        table = _make_table()
        table._children = ["COM_old1", "COM_old2"]
        table._tree.delete = MagicMock()
        table.restore_from_cache({"COM5": {"port_display": "COM5", "status": "IDLE"}})
        self.assertTrue(table._tree.delete.called)


# ------------------------------------------------------------------
# 6. Deleting a row
# ------------------------------------------------------------------

class TestDeleteRow(unittest.TestCase):
    """Deleting a row preserves numeric order of remaining rows."""

    def test_delete_removes_from_cache(self):
        table = _make_table()
        table._row_cache["COM5"] = ["COM5", "-", "-", "-", "IDLE", "-", "-", "LOG"]
        table._children = ["COM5", "COM10"]
        table._tree.exists.return_value = True
        # Mock tree.delete to also remove from _children
        def tree_delete(item):
            if item in table._children:
                table._children.remove(item)
        table._tree.delete.side_effect = tree_delete
        table.delete_row("COM5")
        self.assertNotIn("COM5", table._row_cache)
        self.assertEqual(table._children, ["COM10"])

    def test_delete_nonexistent_is_noop(self):
        table = _make_table()
        table._tree.exists.return_value = False
        table.delete_row("COM999")  # Should not raise


# ------------------------------------------------------------------
# 7. Filter preserves numeric order
# ------------------------------------------------------------------

class TestFilterPreservesOrder(unittest.TestCase):
    """Applying/removing filter preserves numeric order among visible rows."""

    def test_restore_with_filter(self):
        table = _make_table()
        port_states = {
            "COM200": {"port_display": "COM200", "status": "READY"},
            "COM9": {"port_display": "COM9", "status": "IDLE"},
            "COM150": {"port_display": "COM150", "status": "READY"},
        }
        table.restore_from_cache(port_states, filter_fn=lambda p: port_states[p]["status"] == "READY")
        self.assertEqual(table._children, ["COM150", "COM200"])


# ------------------------------------------------------------------
# 8. Selection and LOG identity
# ------------------------------------------------------------------

class TestSelectionAndLogIdentity(unittest.TestCase):
    """Selection and LOG row identity remain valid after reorder."""

    def test_selection_preserved_after_reorder(self):
        table = _make_table()
        table._selected_port = "COM5"
        table._children = ["COM10", "COM5"]  # Out of order
        table._tree.selection.return_value = ("COM5",)
        table._reorder_treeview()
        # Selection restored because reorder happened
        table._tree.selection_set.assert_called()
        self.assertEqual(table._children, ["COM5", "COM10"])

    def test_log_click_identity(self):
        """LOG column click still identifies correct port."""
        table = _make_table()
        table._on_log_click = MagicMock()
        event = MagicMock()
        event.y = 10
        event.x = 500
        table._tree.identify_row.return_value = "COM5"
        table._tree.identify_column.return_value = "#8"
        table._on_left_click(event)
        table._on_log_click.assert_called_once_with("COM5")


# ------------------------------------------------------------------
# 9-13. Neutral states → IDLE + RESPON '-'
# ------------------------------------------------------------------

class TestNeutralStateMapping(unittest.TestCase):
    """All neutral states display as IDLE with RESPON '-'."""

    def test_not_inserted(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("NOT_INSERTED"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("NOT_INSERTED", "SIM Not Inserted"), "-")

    def test_not_ready(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("NOT_READY"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("NOT_READY", "SIM Not Ready"), "-")

    def test_unknown(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("UNKNOWN"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("UNKNOWN", "Detecting SIM"), "-")

    def test_checking(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("CHECKING"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("CHECKING", "Checking..."), "-")

    def test_standby(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("STANDBY"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("STANDBY", "Idle/Standby"), "-")

    def test_idle(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("IDLE"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("IDLE", "Idle/Standby"), "-")

    def test_off(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("OFF"), "IDLE")
        self.assertEqual(PortStatusTable._normalize_respon("OFF", "SIM Not Inserted"), "-")


# ------------------------------------------------------------------
# 14. READY and workflow-result display unchanged
# ------------------------------------------------------------------

class TestReadyAndWorkflowDisplay(unittest.TestCase):
    """READY and workflow results retain their existing presentation."""

    def test_ready_unchanged(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("READY"), "READY")
        self.assertEqual(PortStatusTable._normalize_respon("READY", "SIM Inserted"), "SIM Inserted")

    def test_processing_unchanged(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("PROCESSING"), "PROCESSING")
        self.assertEqual(PortStatusTable._normalize_respon("PROCESSING", "Running..."), "Running...")

    def test_success_unchanged(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("SUCCESS"), "SUCCESS")
        self.assertEqual(PortStatusTable._normalize_respon("SUCCESS", "Selesai"), "Selesai")

    def test_failed_unchanged(self):
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("FAILED"), "FAILED")
        self.assertEqual(PortStatusTable._normalize_respon("FAILED", "Gagal"), "Gagal")

    def test_insert_row_ready_preserves_respon(self):
        """READY state preserves the actual RESPON text."""
        table = _make_table()
        table.insert_row("COM5", ["COM5", "-", "-", "-", "READY", "SIM Inserted", "-", "LOG"])
        # Verify values passed to insert include READY and SIM Inserted
        call_args = table._tree.insert.call_args
        values = call_args.kwargs.get("values")
        self.assertEqual(values[4], "READY")
        self.assertEqual(values[5], "SIM Inserted")


# ------------------------------------------------------------------
# 15. Domain eligibility unchanged
# ------------------------------------------------------------------

class TestDomainEligibilityUnchanged(unittest.TestCase):
    """UI label simplification does not affect domain state or eligibility."""

    def test_neutral_states_in_set(self):
        """All neutral states are recognized."""
        from worker.ui.port_table import _NEUTRAL_STATUSES
        for state in ["IDLE", "STANDBY", "NOT_INSERTED", "NOT_READY", "UNKNOWN", "CHECKING", "OFF"]:
            self.assertIn(state, _NEUTRAL_STATUSES)

    def test_ready_not_in_neutral(self):
        """READY is NOT in neutral set — domain logic unaffected."""
        from worker.ui.port_table import _NEUTRAL_STATUSES
        self.assertNotIn("READY", _NEUTRAL_STATUSES)

    def test_normalize_is_pure_presentation(self):
        """_normalize_status only changes display, not domain semantics."""
        from worker.ui.port_table import PortStatusTable
        self.assertEqual(PortStatusTable._normalize_status("READY"), "READY")
        self.assertEqual(PortStatusTable._normalize_status("PROCESSING"), "PROCESSING")
        self.assertEqual(PortStatusTable._normalize_status("NOT_INSERTED"), "IDLE")


if __name__ == "__main__":
    unittest.main()
