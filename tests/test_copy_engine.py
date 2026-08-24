from __future__ import annotations

from pathlib import Path

from system_core.core import copy_engine


def test_hash_file_digest_is_algorithm_tagged(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("demo\n", encoding="utf-8")

    monkeypatch.setattr(copy_engine, "_blake3_factory", None)
    monkeypatch.setattr(copy_engine, "external_b3sum_path", lambda: None)

    digest = copy_engine.hash_file_blake3(sample)

    assert digest.startswith("sha256:")
    assert len(digest.split(":", 1)[1]) == 64
