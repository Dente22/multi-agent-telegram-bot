"""Schema validation tests."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.tasks import ExtractedTask, Priority, TaskExtractionResult


def test_extracted_task_ok():
    task = ExtractedTask(
        action_item="Prepare weekly report",
        priority=Priority.HIGH,
        assignee="Anna",
        deadline="2026-08-05",
    )
    assert task.deadline == date(2026, 8, 5)


def test_extracted_task_rejects_short_action():
    with pytest.raises(ValidationError):
        ExtractedTask(action_item="ab")


def test_task_extraction_result_defaults():
    result = TaskExtractionResult(tasks=[], confidence=0.5)
    assert result.tasks == []
