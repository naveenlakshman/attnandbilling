"""Regression checks for reversible bad-debt installment allocation."""

from modules.baddebt.routes import _allocate_installment_coverage


def test_deleted_writeoff_restores_receivable():
    allocations = _allocate_installment_coverage([4750, 4750], 2200, 0)
    assert allocations == [(2200.0, 0.0), (0.0, 0.0)]
    assert sum(due - sum(applied) for due, applied in zip([4750, 4750], allocations)) == 7300


def test_full_writeoff_covers_remaining_balance():
    allocations = _allocate_installment_coverage([4750, 4750], 2200, 7300)
    assert allocations == [(2200.0, 2550.0), (0.0, 4750.0)]


def test_partial_writeoff_keeps_uncovered_balance_visible():
    allocations = _allocate_installment_coverage([5000, 5000], 1000, 2500)
    assert allocations == [(1000.0, 2500.0), (0.0, 0.0)]
    assert sum(due - sum(applied) for due, applied in zip([5000, 5000], allocations)) == 6500

