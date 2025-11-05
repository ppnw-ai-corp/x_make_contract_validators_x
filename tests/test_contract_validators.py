from __future__ import annotations

# ruff: noqa: S101
import json
from typing import TYPE_CHECKING, cast

import pytest

from x_make_contract_validators_x.x_cls_make_contract_validators_x import (
    ContractValidationError,
    RunResult,
    SchemaValidationError,
    main,
    run,
    validate_payload,
    validate_schema,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture


def _load_json_object(raw: str) -> dict[str, object]:
    loaded = cast("object", json.loads(raw))
    assert isinstance(loaded, dict)
    return cast("dict[str, object]", loaded)


def _dump_json_object(data: dict[str, object]) -> str:
    # Cast avoids Any propagation from json.dumps and keeps mypy strict happy.
    return json.dumps(cast("object", data))


@pytest.fixture
def sample_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0},
        },
        "required": ["name"],
        "additionalProperties": False,
    }


def test_validate_schema_success(sample_schema: dict[str, object]) -> None:
    validate_schema(sample_schema)


def test_validate_schema_failure() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"value": {"type": "does_not_exist"}},
    }
    with pytest.raises(SchemaValidationError):
        validate_schema(schema)


def test_validate_payload_success(sample_schema: dict[str, object]) -> None:
    result = validate_payload({"name": "Jess", "age": 33}, sample_schema)
    assert result.success is True
    assert result.issues == ()


def test_validate_payload_failure(sample_schema: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError) as exc_info:
        validate_payload({"age": 10}, sample_schema)
    issues = exc_info.value.issues
    assert issues
    first = issues[0]
    assert "is a required property" in first.message
    assert tuple(first.path) == ()


def test_run_inline_payload(sample_schema: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "parameters": {
            "schema": sample_schema,
            "payload": {"name": "Ops"},
        }
    }
    result: RunResult = run(payload)
    assert result["status"] == "success"
    assert result["issues"] == []


def test_run_payload_from_files(
    sample_schema: dict[str, object], tmp_path: Path
) -> None:
    schema_path = tmp_path / "schema.json"
    payload_path = tmp_path / "payload.json"
    schema_path.write_text(_dump_json_object(sample_schema), encoding="utf-8")
    payload_path.write_text(
        _dump_json_object({"name": "Ops", "age": 2}),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "parameters": {
            "schema_path": str(schema_path),
            "payload_path": str(payload_path),
        }
    }
    result: RunResult = run(payload)
    assert result["status"] == "success"


def test_run_failure_details(sample_schema: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "parameters": {
            "schema": sample_schema,
            "payload": {"name": 4},
        }
    }
    result: RunResult = run(payload)
    assert result["status"] == "failure"
    assert result["error_type"] == "payload"
    assert result["issues"]


def test_cli_success(
    sample_schema: dict[str, object],
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    schema_path = tmp_path / "schema.json"
    payload_path = tmp_path / "payload.json"
    schema_path.write_text(_dump_json_object(sample_schema), encoding="utf-8")
    payload_path.write_text(
        _dump_json_object({"name": "CLI"}),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "--schema",
            str(schema_path),
            "--payload",
            str(payload_path),
            "--json",
        ]
    )
    assert exit_code == 0
    output = _load_json_object(capsys.readouterr().out)
    assert output["status"] == "success"


def test_cli_failure(
    sample_schema: dict[str, object],
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    schema_path = tmp_path / "schema.json"
    payload_path = tmp_path / "payload.json"
    schema_path.write_text(_dump_json_object(sample_schema), encoding="utf-8")
    payload_path.write_text(
        _dump_json_object({"age": 5}),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "--schema",
            str(schema_path),
            "--payload",
            str(payload_path),
            "--json",
        ]
    )
    assert exit_code == 1
    output = _load_json_object(capsys.readouterr().out)
    assert output["status"] == "failure"
    assert output["error_type"] == "payload"
