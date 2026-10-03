"""Whether each platform can send an offer, and whether a login is still required."""

from __future__ import annotations

from pathlib import Path

from hk_bazaar.config import Settings


def format_login_report(settings: Settings) -> str:
    facebook_ready = Path(settings.facebook_storage_state).exists()
    carousell_ready = Path(settings.carousell_storage_state).exists()
    asiaxpat_ready = Path(settings.asiaxpat_storage_state).exists()
    dry_run = "on" if settings.outreach_dry_run else "off"
    send_line = (
        "While dry_run is on, approving an offer logs it and does not contact the seller."
        if settings.outreach_dry_run
        else "dry_run is off. Approving an offer contacts the seller on asiaXPAT, Carousell, or Facebook."
    )
    lines = [
        "hk-bazaar logins",
        f"dry_run: {dry_run}",
        "A live asiaXPAT message, Carousell offer, or Facebook message needs that platform's saved login.",
        send_line,
        "",
        f"{'platform':<16} {'offer':<22} {'login':<10} session",
        _row(
            "asiaXPAT",
            "message seller",
            "ready" if asiaxpat_ready else "needed",
            settings.asiaxpat_storage_state,
        ),
        _row(
            "Carousell",
            "make offer",
            "ready" if carousell_ready else "needed",
            settings.carousell_storage_state,
        ),
        _row(
            "Facebook",
            "messenger",
            "ready" if facebook_ready else "needed",
            settings.facebook_storage_state,
        ),
    ]
    return "\n".join(lines) + "\n"


def _row(platform: str, offer: str, login: str, session: object) -> str:
    return f"{platform:<16} {offer:<22} {login:<10} {session}"
