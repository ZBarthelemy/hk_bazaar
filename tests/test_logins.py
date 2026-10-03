"""Login report for optional outreach."""

from pathlib import Path

from hk_bazaar.config import Settings
from hk_bazaar.outreach.readiness import format_login_report


def _settings(
    tmp_path: Path,
    *,
    facebook: bool,
    carousell: bool,
    asiaxpat: bool = False,
    dry_run: bool,
) -> Settings:
    facebook_path = tmp_path / "facebook.json"
    carousell_path = tmp_path / "carousell.json"
    asiaxpat_path = tmp_path / "asiaxpat.json"
    if facebook:
        facebook_path.write_text("{}", encoding="utf-8")
    if carousell:
        carousell_path.write_text("{}", encoding="utf-8")
    if asiaxpat:
        asiaxpat_path.write_text("{}", encoding="utf-8")
    return Settings(
        facebook_storage_state=facebook_path,
        carousell_storage_state=carousell_path,
        asiaxpat_storage_state=asiaxpat_path,
        outreach_dry_run=dry_run,
    )


def test_carousell_needs_login_and_facebook_is_ready(tmp_path: Path) -> None:
    text = format_login_report(_settings(tmp_path, facebook=True, carousell=False, dry_run=True))
    assert "dry_run: on" in text
    assert "asiaXPAT" in text and "needed" in text
    assert "Carousell" in text and "needed" in text
    assert "Facebook" in text and "ready" in text


def test_both_sessions_ready_when_files_exist(tmp_path: Path) -> None:
    text = format_login_report(
        _settings(tmp_path, facebook=True, carousell=True, asiaxpat=True, dry_run=False)
    )
    rows = {line.split()[0]: line for line in text.splitlines() if line[:1].isalpha() and "offer" not in line[:8]}
    assert "dry_run: off" in text
    assert "needed" not in rows["Carousell"]
    assert "ready" in rows["Carousell"]
    assert "ready" in rows["Facebook"]
    assert "ready" in rows["asiaXPAT"]
