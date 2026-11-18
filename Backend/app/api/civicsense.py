import os
import sys
import time
import json
import random
import subprocess
import logging
from typing import Optional
import psutil
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/civicsense", tags=["CivicSense Unified System"])

live_process: Optional[subprocess.Popen] = None
live_source: str = "0"

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT_PATH = os.path.join(WORKSPACE_DIR, "Pothole", "civicsense_all_in_one.py")
STATE_FILE = os.path.join(WORKSPACE_DIR, "Pothole", "civicsense_live_state.json")

POTHOLE_VENV_PYTHON = os.path.join(WORKSPACE_DIR, "Pothole", ".venv", "Scripts", "python.exe")
BACKEND_VENV_PYTHON = os.path.join(WORKSPACE_DIR, "Backend", "venv", "Scripts", "python.exe")
if os.path.exists(POTHOLE_VENV_PYTHON):
    PYTHON_EXE = POTHOLE_VENV_PYTHON
elif os.path.exists(BACKEND_VENV_PYTHON):
    PYTHON_EXE = BACKEND_VENV_PYTHON
else:
    PYTHON_EXE = sys.executable


class LiveStartRequest(BaseModel):
    source: str = "0"
    esp_ip: str = "192.168.206.33"
    enable_esp: bool = True
    headless: bool = False


class SimulateRequest(BaseModel):
    hazard_type: str = "pothole"  # "pothole", "fire", "smoke", "overflow", "normal", "random"


@router.post("/start-live")
async def start_live_civicsense(req: LiveStartRequest):
    """
    Triggers civicsense_all_in_one.py to launch unified multi-model detection:
    - Pothole Detection (YOLO11n)
    - Fire & Smoke Detection (YOLO11n)
    - Waste Bin Overflow (CLIP)
    - Real-time ESP32 hardware alert synchronization
    """
    global live_process, live_source

    # Check if already running
    if live_process and live_process.poll() is None:
        return {
            "status": "ALREADY_RUNNING",
            "pid": live_process.pid,
            "source": live_source,
            "message": f"CivicSense is already running (PID: {live_process.pid})"
        }

    if not os.path.exists(SCRIPT_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Script not found at {SCRIPT_PATH}"
        )

    # Resolve video source if relative to Pothole folder
    src = str(req.source).strip()
    if src not in ["0", "1", "2"] and not src.startswith("http") and not os.path.isabs(src):
        candidate = os.path.join(WORKSPACE_DIR, "Pothole", src)
        if os.path.exists(candidate):
            src = candidate

    cmd = [
        PYTHON_EXE,
        SCRIPT_PATH,
        "--source", src,
        "--esp-ip", str(req.esp_ip),
    ]
    if not req.enable_esp:
        cmd.append("--no-esp")
    if req.headless:
        cmd.append("--headless")

    logger.info("Triggering civicsense_all_in_one.py: %s", " ".join(cmd))
    try:
        live_process = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(SCRIPT_PATH),
            shell=False
        )
        live_source = str(req.source)
        return {
            "status": "RUNNING",
            "pid": live_process.pid,
            "source": live_source,
            "message": f"CivicSense Unified AI Engine triggered (PID: {live_process.pid})"
        }
    except Exception as e:
        logger.error("Failed to trigger civicsense_all_in_one.py: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start CivicSense engine: {str(e)}"
        )


@router.post("/stop-live")
async def stop_live_civicsense():
    """Stops the active civicsense_all_in_one.py process cleanly."""
    global live_process
    if not live_process or live_process.poll() is not None:
        live_process = None
        # Also clean up state file
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    curr = json.load(f)
                curr["running"] = False
                curr["status"] = "STOPPED"
                curr["timestamp"] = time.time()
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(curr, f)
            except Exception:
                pass
        return {"status": "STOPPED", "message": "No active CivicSense process running"}

    pid = live_process.pid
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.terminate()
        parent.terminate()
        live_process.wait(timeout=2)
    except Exception:
        try:
            live_process.kill()
        except Exception:
            pass

    live_process = None
    logger.info("Stopped CivicSense live engine process (PID: %s)", pid)
    return {"status": "STOPPED", "message": f"CivicSense process {pid} terminated"}


@router.get("/status")
async def get_civicsense_status():
    """Returns the operational status and real-time detection telemetry of civicsense_all_in_one.py."""
    global live_process, live_source

    is_proc_running = live_process is not None and live_process.poll() is None

    state_data = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception as e:
            logger.warning("Could not read civicsense state file: %s", e)

    # Check freshness (if updated within the last 4.5 seconds, or 60 seconds if simulated)
    is_fresh = False
    if state_data:
        ts = state_data.get("timestamp", 0)
        is_sim = state_data.get("is_simulated", False)
        timeout = 60.0 if is_sim else 4.5
        if state_data.get("running", False) and (time.time() - ts) < timeout:
            is_fresh = True

    is_running = is_proc_running or is_fresh

    if not state_data:
        state_data = {
            "running": False,
            "status": "STANDBY",
            "source": live_source,
            "fps": 0.0,
            "frame_idx": 0,
            "primary_hazard": None,
            "pothole": {
                "detected": False,
                "count": 0,
                "confidence": 0.0,
                "status": "CLEAR",
                "bboxes": []
            },
            "fire_smoke": {
                "detected": False,
                "fire_detected": False,
                "smoke_detected": False,
                "confidence": 0.0,
                "status": "CLEAR",
                "bboxes": []
            },
            "overflow": {
                "detected": False,
                "status": "NORMAL",
                "confidence": 0.0,
                "label": "Clean / normal waste bin"
            },
            "esp32": {
                "enabled": True,
                "ip": "192.168.206.33",
                "last_msg": "Idle",
                "active_signal": "normal"
            },
            "total_incidents": 0,
            "recent_incidents": []
        }
    else:
        state_data["running"] = is_running
        if not is_running and state_data.get("status") in ["STARTING", "RUNNING"]:
            state_data["status"] = "STANDBY"

    state_data["pid"] = live_process.pid if is_proc_running else None
    state_data["script"] = SCRIPT_PATH
    return state_data


@router.post("/simulate")
async def simulate_event(req: SimulateRequest):
    """
    Simulates model detections to test the 3 cards in real time without requiring
    an active camera or video file stream.
    """
    ht = req.hazard_type.lower()
    now_t = time.time()

    is_pothole = ht in ["pothole", "all"] or (ht == "random" and random.random() > 0.5)
    is_fire = ht in ["fire", "all"] or (ht == "random" and random.random() > 0.7)
    is_smoke = ht in ["smoke", "all"] or (ht == "random" and random.random() > 0.6)
    is_overflow = ht in ["overflow", "all"] or (ht == "random" and random.random() > 0.5)

    primary_hazard = None
    if is_fire:
        primary_hazard = "fire"
    elif is_smoke:
        primary_hazard = "smoke"
    elif is_pothole:
        primary_hazard = "pothole"
    elif is_overflow:
        primary_hazard = "overflow"

    sim_state = {
        "running": True,
        "is_simulated": True,
        "timestamp": now_t,
        "source": "SIMULATED_TEST_STREAM",
        "fps": 25.0,
        "frame_idx": int(now_t * 10) % 10000,
        "primary_hazard": primary_hazard,
        "pothole": {
            "detected": is_pothole,
            "count": 2 if is_pothole else 0,
            "confidence": round(0.85 + random.uniform(-0.05, 0.1), 3) if is_pothole else 0.0,
            "status": "POTHOLE_DETECTED" if is_pothole else "CLEAR",
            "bboxes": [[145, 320, 310, 450, 0.89], [420, 380, 560, 480, 0.82]] if is_pothole else []
        },
        "fire_smoke": {
            "detected": is_fire or is_smoke,
            "fire_detected": is_fire,
            "smoke_detected": is_smoke,
            "confidence": round(0.92 + random.uniform(-0.04, 0.06), 3) if (is_fire or is_smoke) else 0.0,
            "status": "FIRE_ALERT" if is_fire else ("SMOKE_ALERT" if is_smoke else "CLEAR"),
            "bboxes": [[210, 150, 380, 340, 0.94, "FIRE"]] if is_fire else ([[180, 100, 400, 280, 0.88, "SMOKE"]] if is_smoke else [])
        },
        "overflow": {
            "detected": is_overflow,
            "status": "OVERFLOW" if is_overflow else "NORMAL",
            "confidence": round(0.88 + random.uniform(-0.06, 0.08), 3) if is_overflow else round(0.12 + random.uniform(0, 0.1), 3),
            "label": "Overflowing waste bin with garbage spilling" if is_overflow else "Clean / normal waste bin"
        },
        "esp32": {
            "enabled": True,
            "ip": "192.168.206.33",
            "last_msg": f"Sent /{primary_hazard} (200)" if primary_hazard else "Sent /normal (200)",
            "active_signal": primary_hazard or "normal"
        },
        "total_incidents": 8 if (is_pothole or is_fire or is_overflow) else 0
    }

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sim_state, f)
    except Exception as e:
        logger.error("Could not write simulated state: %s", e)

    return sim_state
