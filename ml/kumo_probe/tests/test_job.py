"""The Modal entry point is checked as source. Tests do not import modal or start a GPU."""

from __future__ import annotations

from pathlib import Path

from kumo_probe.remote import ensure_dbt_on_venv_path


def _job_source() -> str:
    return (Path(__file__).resolve().parents[1] / "modal_job.py").read_text(encoding="utf-8")


def test_modal_entry_mounts_a_volume_and_scores_on_l4() -> None:
    text = _job_source()
    cpu, gpu = text.split("gpu_image =", 1)
    assert "structured-data-models" not in cpu
    assert "git+https://github.com/NVIDIA/structured-data-models.git" in gpu
    assert 'gpu="L4"' in gpu
    assert "beta-aid-kumo-data" in text
    assert "Volume.from_name" in text
    assert 'LATAM_EDA_DATA": "/data"' in text
    assert "add_local_dir(REPO," not in text
    assert 'REPO / "data"' not in text
    assert 'REPO / ".env"' not in text
    assert "add_local_dir(REPO /" in text


def test_dbt_binary_is_symlinked_where_the_gate_expects_it(tmp_path: Path) -> None:
    repo = tmp_path
    binary = tmp_path / "installed" / "dbt"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    def _which(name: str) -> str | None:
        assert name == "dbt"
        return str(binary)

    import kumo_probe.remote as remote

    original = remote.shutil.which
    remote.shutil.which = _which
    try:
        ensure_dbt_on_venv_path(repo)
        expected = repo / "platform" / ".venv" / "bin" / "dbt"
        assert expected.is_symlink()
        assert expected.resolve() == binary.resolve()
        ensure_dbt_on_venv_path(repo)
        assert expected.is_symlink()
    finally:
        remote.shutil.which = original
