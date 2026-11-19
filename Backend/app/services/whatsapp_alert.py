"""
WhatsApp Alert Service via Twilio
Sends WhatsApp notifications to admin when an incident (Fire, Smoke, Pothole,
Waste Bin Overflow) is detected and saved to the database.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Lazy import so the app still works even if twilio is not installed yet
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.warning("Twilio library not installed. WhatsApp alerts are disabled.")

from app.core.config import settings


# ── Incident type display helpers ──────────────────────────────────────────────

INCIDENT_EMOJI = {
    "FIRE":               "🔥",
    "SMOKE":              "🌫️",
    "POTHOLE":            "🕳️",
    "WASTE_BIN_OVERFLOW": "🗑️",
}

INCIDENT_LABEL = {
    "FIRE":               "Fire Detected",
    "SMOKE":              "Smoke Detected",
    "POTHOLE":            "Pothole Detected",
    "WASTE_BIN_OVERFLOW": "Waste Bin Overflow",
}


def _build_message(incident: Dict[str, Any]) -> str:
    """Format a human-readable WhatsApp alert message from incident data."""
    inc_type    = incident.get("incident_type", "UNKNOWN")
    emoji       = INCIDENT_EMOJI.get(inc_type, "⚠️")
    label       = INCIDENT_LABEL.get(inc_type, inc_type.replace("_", " ").title())
    confidence  = incident.get("confidence", 0.0)
    camera      = incident.get("camera_name", "Unknown Camera")
    source_type = incident.get("source_type", "")
    snapshot    = incident.get("snapshot_url") or "N/A"
    inc_id      = incident.get("_id", "N/A")

    # Format timestamp
    detected_at = incident.get("incident_detected_at")
    if isinstance(detected_at, datetime):
        time_str = detected_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    elif isinstance(detected_at, str):
        time_str = detected_at
    else:
        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    source_line = f"📷 Source: {camera}" if source_type == "LIVE_CAMERA" else f"📁 Source: {source_type}"

    message = (
        f"{emoji} *Vision Civic — Incident Alert*\n\n"
        f"*Type:* {label}\n"
        f"*Confidence:* {confidence * 100:.1f}%\n"
        f"{source_line}\n"
        f"*Detected At:* {time_str}\n"
        f"*Incident ID:* {inc_id}\n"
    )

    if snapshot != "N/A":
        message += f"\n📸 *Snapshot:* {snapshot}"

    message += "\n\n_Please review the Vision Civic dashboard immediately._"
    return message


def send_whatsapp_alert(incident: Dict[str, Any]) -> bool:
    """
    Send a WhatsApp alert message to the admin phone number.

    Returns True on success, False on failure (never raises).
    """
    if not TWILIO_AVAILABLE:
        logger.error("Twilio is not installed. Run: pip install twilio")
        return False

    # Validate required Twilio settings
    if not all([
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
        settings.TWILIO_WHATSAPP_FROM,
        settings.ADMIN_WHATSAPP_TO,
    ]):
        logger.error(
            "WhatsApp alert skipped: Missing Twilio credentials or admin phone in .env. "
            "Required: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "TWILIO_WHATSAPP_FROM, ADMIN_WHATSAPP_TO"
        )
        return False

    try:
        client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        body   = _build_message(incident)

        msg = client.messages.create(
            from_=f"whatsapp:{settings.TWILIO_WHATSAPP_FROM}",
            to=f"whatsapp:{settings.ADMIN_WHATSAPP_TO}",
            body=body,
        )

        logger.info(
            "[WhatsApp Alert] Sent for incident %s → SID: %s",
            incident.get("incident_type"), msg.sid
        )
        return True

    except Exception as e:
        logger.error("[WhatsApp Alert] Failed to send: %s", e, exc_info=True)
        return False


async def send_whatsapp_alert_async(incident: Dict[str, Any]) -> bool:
    """
    Async-safe wrapper — runs the blocking Twilio call in a thread pool
    so it never blocks the FastAPI event loop.
    """
    import asyncio
    return await asyncio.to_thread(send_whatsapp_alert, incident)
