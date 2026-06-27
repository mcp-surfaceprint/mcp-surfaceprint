from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_preflight import _canonicalize_surface, _compute_surface_digest, _compute_surface_changes


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "conformance"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _record_matches_subset(record: dict, expected: dict) -> bool:
    for k, v in expected.items():
        if k not in record:
            return False
        if record[k] != v:
            return False
    return True


def test_conformance_canonical_basic_surface_golden() -> None:
    fx = _load_json(FIXTURES_DIR / "canonical" / "basic_surface.json")
    surface = fx["surface"]
    expected_canonical = fx["expectedCanonical"]
    expected_digest = fx["expectedDigest"]

    canon = _canonicalize_surface(surface)
    assert canon == expected_canonical
    assert _compute_surface_digest(surface) == expected_digest


def test_conformance_equivalence_reordered_manifest_ops_and_prompt_args() -> None:
    fx = _load_json(FIXTURES_DIR / "equivalence" / "reordered_manifest_ops_and_prompt_args.json")
    a = fx["a"]
    b = fx["b"]

    da = _compute_surface_digest(a)
    db = _compute_surface_digest(b)
    assert da == db

    changes = _compute_surface_changes(a, b)
    assert changes == []


def test_conformance_changes_manifest_operation_added() -> None:
    fx = _load_json(FIXTURES_DIR / "changes" / "manifest_operation_added.json")
    before = fx["before"]
    after = fx["after"]

    assert _compute_surface_digest(before) != _compute_surface_digest(after)

    changes = _compute_surface_changes(before, after)
    assert changes

    expected = fx["expectedRecords"]
    for exp in expected:
        assert any(_record_matches_subset(c, exp) for c in changes)


def test_conformance_changes_resource_description_changed() -> None:
    fx = _load_json(FIXTURES_DIR / "changes" / "resource_description_changed.json")
    before = fx["before"]
    after = fx["after"]

    assert _compute_surface_digest(before) != _compute_surface_digest(after)

    changes = _compute_surface_changes(before, after)
    assert changes

    expected = fx["expectedRecords"]
    for exp in expected:
        assert any(_record_matches_subset(c, exp) for c in changes)


def test_conformance_changes_tool_schema_enum_expanded() -> None:
    fx = _load_json(FIXTURES_DIR / "changes" / "tool_schema_enum_expanded.json")
    before = fx["before"]
    after = fx["after"]

    assert _compute_surface_digest(before) != _compute_surface_digest(after)

    changes = _compute_surface_changes(before, after)
    assert changes

    expected = fx["expectedRecords"]
    for exp in expected:
        assert any(_record_matches_subset(c, exp) for c in changes)


def test_digest_diff_equivalence_invariant_for_complete_surfaces() -> None:
    """
    Release-blocking invariant for complete surfaces:

    digest_equal == changes_empty
    """
    # Use representative pairs from fixtures (equivalence + changes).
    equiv = _load_json(FIXTURES_DIR / "equivalence" / "reordered_manifest_ops_and_prompt_args.json")
    pairs = [
        (equiv["a"], equiv["b"]),
    ]
    for name in ("manifest_operation_added", "resource_description_changed", "tool_schema_enum_expanded"):
        fx = _load_json(FIXTURES_DIR / "changes" / f"{name}.json")
        pairs.append((fx["before"], fx["after"]))

    for before, after in pairs:
        digest_equal = _compute_surface_digest(before) == _compute_surface_digest(after)
        changes_empty = _compute_surface_changes(before, after) == []
        assert digest_equal == changes_empty


def _iter_mutation_targets(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k in sorted(obj.keys()):
            p = f"{prefix}/{k}" if prefix else f"/{k}"
            yield from _iter_mutation_targets(obj[k], p)
        return
    if isinstance(obj, list):
        # Only treat lists-of-primitives as a mutatable leaf container.
        # Lists that contain dicts/lists are traversed, but not mutated as a whole here,
        # because canonicalization may drop nonconforming entries (e.g. declarationSources).
        if all(not isinstance(x, (dict, list)) for x in obj):
            yield (prefix or "/", obj)
        for i, v in enumerate(obj):
            p = f"{prefix}/{i}" if prefix else f"/{i}"
            yield from _iter_mutation_targets(v, p)
        return
    # Primitive leaf (including None/bool/int/float/str)
    yield (prefix or "/", obj)


def _mutate_leaf(value: Any) -> Any:
    if isinstance(value, str):
        return value + "_mut"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if value is None:
        return "mut"
    if isinstance(value, list):
        return list(value) + ["mut"]
    # Fallback: coerce to string
    return _mutate_leaf(str(value))


def _set_at_path(root: Any, path: str, new_value: Any) -> Any:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return new_value
    cur = root
    for p in parts[:-1]:
        if isinstance(cur, dict):
            cur = cur[p]
        else:
            cur = cur[int(p)]
    last = parts[-1]
    if isinstance(cur, dict):
        cur[last] = new_value
    else:
        cur[int(last)] = new_value
    return root


def test_mutation_coverage_invariant_identity_bearing_leaves() -> None:
    """
    Mutation-coverage invariant:

    Any identity-bearing canonical leaf change must:
    - change the surfaceDigest
    - produce at least one change record
    """
    fx = _load_json(FIXTURES_DIR / "canonical" / "basic_surface.json")
    base_surface = fx["surface"]
    base_canon = _canonicalize_surface(base_surface)
    base_digest = _compute_surface_digest(base_surface)

    # Canonical surfaces should be JSON-safe; deep copy via round-trip.
    for path, old in list(_iter_mutation_targets(base_canon)):
        mutated = json.loads(json.dumps(base_canon, ensure_ascii=False))
        new_val = _mutate_leaf(old)
        _set_at_path(mutated, path, new_val)

        mutated_digest = _compute_surface_digest(mutated)
        assert mutated_digest != base_digest, f"digest did not change for mutation at {path}"

        changes = _compute_surface_changes(base_canon, mutated)
        assert changes, f"no change records for mutation at {path}"

