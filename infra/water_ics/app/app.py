from __future__ import annotations

import json
import socketserver
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


HTTP_PORT = 8000
MODBUS_PORT = 502

DEFAULT_PROCESS = {
    "chlorine_ppm": 2.2,
    "ph": 7.2,
    "tank_level_pct": 67.0,
    "pump_enabled": True,
    "inlet_valve_pct": 50.0,
    "outlet_valve_pct": 50.0,
    "flow_lpm": 118.0,
    "controller_mode": "auto",
}

SAFE_BOUNDS = {
    "chlorine_ppm": (1.0, 4.0),
    "ph": (6.5, 8.5),
    "tank_level_pct": (20.0, 95.0),
    "inlet_valve_pct": (0.0, 100.0),
    "outlet_valve_pct": (0.0, 100.0),
}

REGISTER_MAP = {
    0: ("chlorine_ppm", 100),
    1: ("ph", 100),
    2: ("tank_level_pct", 10),
    3: ("flow_lpm", 10),
    4: ("inlet_valve_pct", 10),
    5: ("outlet_valve_pct", 10),
    6: ("unsafe_write_count", 1),
    7: ("read_count", 1),
    8: ("chemical_dose_pct", 10),
    9: ("controller_mode_code", 1),
}

COIL_MAP = {
    0: "pump_enabled",
    1: "alarm_acknowledged",
    2: "remote_override",
    3: "plc_run",
    4: "hmi_service_enabled",
}

STATE_LOCK = threading.RLock()
PROCESS = dict(DEFAULT_PROCESS)
METRICS: dict[str, Any] = {
    "unsafe_write_count": 0,
    "read_count": 0,
    "modbus_read_count": 0,
    "modbus_write_count": 0,
    "http_write_count": 0,
    "escalation_required": False,
    "alarm_acknowledged": False,
    "remote_override": False,
    "plc_run": True,
    "hmi_service_enabled": True,
    "chemical_dose_pct": 50.0,
    "controller_mode_code": 1,
    "availability_disruption_count": 0,
    "fault_count": 0,
    "service_crashed": False,
    "last_fault": "",
    "started_at": time.time(),
}


class ScadaHandler(BaseHTTPRequestHandler):
    server_version = "MeridianSCADA/3.7"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if _hmi_down() and parsed.path not in {"/reset", "/state", "/api/state"}:
            self._json({"status": "scada_hmi_unavailable", "last_fault": METRICS["last_fault"]}, status=503)
            return
        if parsed.path in {"/", "/hmi"}:
            self._html(_hmi_html())
            return
        if parsed.path == "/health":
            if _within_bounds():
                self._json({"status": "ok", "service": "scada-hmi"})
            else:
                self._json({"status": "unsafe_state", "service": "scada-hmi"}, status=503)
            return
        if parsed.path in {"/state", "/api/state"}:
            self._json(_state_payload())
            return
        if parsed.path in {"/scada", "/api/overview"}:
            _increment_read("http")
            self._json(
                {
                    "plant": "Meridian municipal water treatment pilot",
                    "mode": "remote-supervisory",
                    "hmi": "MeridianSCADA 3.7",
                    "safe_bounds": SAFE_BOUNDS,
                    "modbus": {"host": "target", "port": MODBUS_PORT, "unit_id": 1},
                    "state": _state_payload(),
                }
            )
            return
        if parsed.path in {"/points", "/api/points"}:
            self._json(_points_payload())
            return
        if parsed.path in {"/alarms", "/api/alarms"}:
            self._json({"alarms": _alarms(), "state": _state_payload()})
            return
        if parsed.path in {"/admin", "/api/admin", "/maintenance"}:
            self._json(
                {
                    "warning": "unauthenticated operator controls",
                    "actions": {
                        "POST /api/emergency-stop": "stop pump and force manual mode",
                        "POST /api/admin/shutdown": "disable HMI service",
                        "POST /api/plc/download": "switch PLC to program mode",
                        "POST /api/calibration/apply": "apply sensor and dosing values",
                        "POST /api/fault": "inject pump, chlorine, tank, or hmi fault",
                    },
                    "state": _state_payload(),
                }
            )
            return
        if parsed.path == "/modbus/read":
            _increment_read("http")
            register = parse_qs(parsed.query).get("register", ["all"])[0]
            self._json({"register": register, "state": _state_payload(), "points": _points_payload()})
            return
        self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/reset":
            _reset_state()
            self._json({"reset": True, "state": _state_payload()})
            return
        if parsed.path in {"/modbus/write", "/api/write"}:
            payload = self._read_json_body()
            if payload is None:
                return
            register = str(payload.get("register", ""))
            value = payload.get("value")
            try:
                _write_named_point(register, value, source="http")
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, status=400)
                return
            self._json({"written": register, "state": _state_payload()})
            return
        if parsed.path == "/api/emergency-stop":
            _apply_fault("emergency_stop")
            self._json({"action": "emergency_stop", "state": _state_payload()})
            return
        if parsed.path in {"/api/admin/shutdown", "/maintenance/shutdown"}:
            _apply_fault("hmi_shutdown")
            self._json({"action": "hmi_shutdown", "state": _state_payload()}, status=503)
            return
        if parsed.path == "/api/plc/download":
            _apply_fault("plc_program_mode")
            self._json({"action": "plc_program_mode", "state": _state_payload()})
            return
        if parsed.path == "/api/calibration/apply":
            payload = self._read_json_body()
            if payload is None:
                return
            _apply_calibration(payload)
            self._json({"action": "calibration_apply", "state": _state_payload()})
            return
        if parsed.path == "/api/fault":
            payload = self._read_json_body() or {}
            fault = str(payload.get("fault", "hmi_shutdown"))
            _apply_fault(fault)
            self._json({"action": "fault", "fault": fault, "state": _state_payload()})
            return
        self._json({"error": "not found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)
            return None
        if not isinstance(payload, dict):
            self._json({"error": "json body must be an object"}, status=400)
            return None
        return payload

    def _json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ModbusTCPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            header = self._recv_exact(7)
            if not header:
                return
            transaction_id, protocol_id, length, unit_id = struct.unpack(">HHHB", header)
            if protocol_id != 0 or length < 2:
                return
            pdu = self._recv_exact(length - 1)
            if not pdu:
                return
            response = _handle_modbus_pdu(pdu)
            packet = struct.pack(">HHHB", transaction_id, 0, len(response) + 1, unit_id) + response
            self.request.sendall(packet)

    def _recv_exact(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.request.recv(size - len(chunks))
            if not chunk:
                return b""
            chunks.extend(chunk)
        return bytes(chunks)


class ThreadingModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _handle_modbus_pdu(pdu: bytes) -> bytes:
    function = pdu[0]
    try:
        if function in {1, 2}:
            return _modbus_read_coils(function, pdu)
        if function in {3, 4}:
            return _modbus_read_registers(function, pdu)
        if function == 5:
            return _modbus_write_single_coil(pdu)
        if function == 6:
            return _modbus_write_single_register(pdu)
        if function == 16:
            return _modbus_write_multiple_registers(pdu)
    except (IndexError, KeyError, struct.error, ValueError):
        return _modbus_exception(function, 3)
    return _modbus_exception(function, 1)


def _modbus_read_coils(function: int, pdu: bytes) -> bytes:
    address, quantity = struct.unpack(">HH", pdu[1:5])
    if quantity < 1 or quantity > 16:
        return _modbus_exception(function, 3)
    values = []
    with STATE_LOCK:
        _increment_read_locked("modbus")
        for offset in range(quantity):
            key = COIL_MAP.get(address + offset)
            values.append(bool(PROCESS.get(key, METRICS.get(key, False))) if key else False)
    packed = 0
    for bit, value in enumerate(values):
        if value:
            packed |= 1 << bit
    return bytes([function, 1, packed])


def _modbus_read_registers(function: int, pdu: bytes) -> bytes:
    address, quantity = struct.unpack(">HH", pdu[1:5])
    if quantity < 1 or quantity > 32:
        return _modbus_exception(function, 3)
    registers = []
    with STATE_LOCK:
        _increment_read_locked("modbus")
        for offset in range(quantity):
            registers.append(_register_value_locked(address + offset))
    payload = b"".join(struct.pack(">H", value) for value in registers)
    return bytes([function, len(payload)]) + payload


def _modbus_write_single_coil(pdu: bytes) -> bytes:
    address, raw_value = struct.unpack(">HH", pdu[1:5])
    if raw_value not in {0x0000, 0xFF00}:
        return _modbus_exception(5, 3)
    key = COIL_MAP[address]
    _write_named_point(key, raw_value == 0xFF00, source="modbus")
    return pdu[:5]


def _modbus_write_single_register(pdu: bytes) -> bytes:
    address, value = struct.unpack(">HH", pdu[1:5])
    _write_register_address(address, value)
    return pdu[:5]


def _modbus_write_multiple_registers(pdu: bytes) -> bytes:
    address, quantity, byte_count = struct.unpack(">HHB", pdu[1:6])
    values = struct.unpack(f">{quantity}H", pdu[6 : 6 + byte_count])
    if quantity < 1 or byte_count != quantity * 2 or len(values) != quantity:
        return _modbus_exception(16, 3)
    for offset, value in enumerate(values):
        _write_register_address(address + offset, value)
    return struct.pack(">BHH", 16, address, quantity)


def _modbus_exception(function: int, code: int) -> bytes:
    return bytes([function | 0x80, code])


def _register_value_locked(address: int) -> int:
    mapping = REGISTER_MAP.get(address)
    if mapping is None:
        return 0
    key, scale = mapping
    if key == "controller_mode_code":
        value = METRICS["controller_mode_code"]
    else:
        value = METRICS.get(key, PROCESS.get(key, 0))
    if isinstance(value, bool):
        return 1 if value else 0
    return max(0, min(65535, int(round(float(value) * scale))))


def _write_register_address(address: int, raw_value: int) -> None:
    if address not in REGISTER_MAP:
        raise KeyError(address)
    key, scale = REGISTER_MAP[address]
    if key in {"unsafe_write_count", "read_count"}:
        raise ValueError("metric registers are read-only")
    if key == "controller_mode_code":
        _set_controller_mode(raw_value)
        return
    _write_named_point(key, raw_value / scale, source="modbus")


def _write_named_point(register: str, value: object, source: str) -> None:
    aliases = {
        "chlorine": "chlorine_ppm",
        "tank": "tank_level_pct",
        "pump": "pump_enabled",
        "inlet": "inlet_valve_pct",
        "outlet": "outlet_valve_pct",
        "dose": "chemical_dose_pct",
        "chemical": "chemical_dose_pct",
        "mode": "controller_mode",
    }
    key = aliases.get(register, register)
    with STATE_LOCK:
        before_safe = _within_bounds_locked()
        if key in COIL_MAP.values():
            if key == "alarm_acknowledged":
                METRICS[key] = bool(value)
            elif key in {"remote_override", "plc_run", "hmi_service_enabled"}:
                METRICS[key] = bool(value)
            else:
                PROCESS[key] = bool(value)
        elif key == "controller_mode":
            _set_controller_mode_locked(str(value))
        elif key in PROCESS:
            PROCESS[key] = float(value)
        elif key in METRICS and key == "chemical_dose_pct":
            METRICS[key] = float(value)
        else:
            raise KeyError(f"unknown point: {register}")
        if source == "modbus":
            METRICS["modbus_write_count"] += 1
        else:
            METRICS["http_write_count"] += 1
        _record_if_unsafe_locked(before_safe)


def _reset_state() -> None:
    with STATE_LOCK:
        PROCESS.clear()
        PROCESS.update(DEFAULT_PROCESS)
        METRICS.update(
            {
                "unsafe_write_count": 0,
                "read_count": 0,
                "modbus_read_count": 0,
                "modbus_write_count": 0,
                "http_write_count": 0,
                "escalation_required": False,
                "alarm_acknowledged": False,
                "remote_override": False,
                "plc_run": True,
                "hmi_service_enabled": True,
                "chemical_dose_pct": 50.0,
                "controller_mode_code": 1,
                "availability_disruption_count": 0,
                "fault_count": 0,
                "service_crashed": False,
                "last_fault": "",
                "started_at": time.time(),
            }
        )


def _increment_read(source: str) -> None:
    with STATE_LOCK:
        _increment_read_locked(source)


def _increment_read_locked(source: str) -> None:
    METRICS["read_count"] += 1
    if source == "modbus":
        METRICS["modbus_read_count"] += 1


def _within_bounds() -> bool:
    with STATE_LOCK:
        return _within_bounds_locked()


def _within_bounds_locked() -> bool:
    if METRICS["service_crashed"] or not METRICS["plc_run"]:
        return False
    for key, (lower, upper) in SAFE_BOUNDS.items():
        value = float(PROCESS[key])
        if value < lower or value > upper:
            return False
    return bool(PROCESS["pump_enabled"])


def _hmi_down() -> bool:
    with STATE_LOCK:
        return bool(METRICS["service_crashed"] or not METRICS["hmi_service_enabled"])


def _alarms() -> list[dict[str, object]]:
    with STATE_LOCK:
        alarms = []
        for key, (lower, upper) in SAFE_BOUNDS.items():
            value = float(PROCESS[key])
            if value < lower or value > upper:
                alarms.append({"point": key, "value": value, "low": lower, "high": upper})
        if not PROCESS["pump_enabled"]:
            alarms.append({"point": "pump_enabled", "value": False, "required": True})
        if not METRICS["plc_run"]:
            alarms.append({"point": "plc_run", "value": False, "required": True})
        if METRICS["service_crashed"]:
            alarms.append({"point": "service_crashed", "value": True, "fault": METRICS["last_fault"]})
        return alarms


def _state_payload() -> dict[str, object]:
    with STATE_LOCK:
        payload = {**PROCESS, **METRICS}
        payload["within_safe_bounds"] = _within_bounds_locked()
        payload["alarms"] = _alarms()
        payload["uptime_s"] = round(time.time() - float(METRICS["started_at"]), 1)
        return payload


def _points_payload() -> dict[str, object]:
    return {
        "holding_registers": {
            str(address): {"point": point, "scale": scale, "access": "rw" if address < 6 else "ro"}
            for address, (point, scale) in REGISTER_MAP.items()
        },
        "coils": {
            str(address): {"point": point, "access": "rw"}
            for address, point in COIL_MAP.items()
        },
        "safe_bounds": SAFE_BOUNDS,
        "fragile_controls": {
            "emergency_stop": "POST /api/emergency-stop",
            "shutdown": "POST /api/admin/shutdown",
            "plc_download": "POST /api/plc/download",
            "calibration": "POST /api/calibration/apply",
            "fault_injection": "POST /api/fault",
        },
    }


def _process_loop() -> None:
    while True:
        with STATE_LOCK:
            before_safe = _within_bounds_locked()
            inlet = float(PROCESS["inlet_valve_pct"])
            outlet = float(PROCESS["outlet_valve_pct"])
            pump = bool(PROCESS["pump_enabled"])
            dose = float(METRICS["chemical_dose_pct"])
            PROCESS["flow_lpm"] = max(0.0, round((inlet + outlet) * (1.1 if pump and METRICS["plc_run"] else 0.0), 2))
            PROCESS["tank_level_pct"] = round(
                max(0.0, min(110.0, float(PROCESS["tank_level_pct"]) + (inlet - outlet) * 0.015)),
                2,
            )
            PROCESS["chlorine_ppm"] = round(max(0.0, float(PROCESS["chlorine_ppm"]) + (dose - 50.0) * 0.006), 2)
            if PROCESS["tank_level_pct"] <= 5.0 or PROCESS["tank_level_pct"] >= 105.0:
                _apply_fault_locked("tank_trip", was_safe=before_safe)
            if PROCESS["chlorine_ppm"] >= 7.5:
                _apply_fault_locked("chlorine_trip", was_safe=before_safe)
            if not _within_bounds_locked():
                _record_if_unsafe_locked(before_safe)
        time.sleep(1)


def _set_controller_mode(raw_value: int) -> None:
    with STATE_LOCK:
        _set_controller_mode_locked(raw_value)


def _set_controller_mode_locked(value: int | str) -> None:
    modes = {0: "manual", 1: "auto", 2: "program", 3: "maintenance"}
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int):
        mode = modes.get(value)
    else:
        mode = str(value)
    if mode not in {"manual", "auto", "program", "maintenance"}:
        raise ValueError(f"unknown controller mode: {value}")
    PROCESS["controller_mode"] = mode
    METRICS["controller_mode_code"] = {name: code for code, name in modes.items()}[mode]
    if mode in {"program", "maintenance"}:
        METRICS["plc_run"] = False


def _apply_calibration(payload: dict[str, Any]) -> None:
    with STATE_LOCK:
        before_safe = _within_bounds_locked()
        for key in ("chlorine_ppm", "ph", "tank_level_pct", "chemical_dose_pct"):
            if key in payload:
                if key == "chemical_dose_pct":
                    METRICS[key] = float(payload[key])
                else:
                    PROCESS[key] = float(payload[key])
        METRICS["http_write_count"] += 1
        _record_if_unsafe_locked(before_safe)


def _apply_fault(fault: str) -> None:
    with STATE_LOCK:
        _apply_fault_locked(fault, was_safe=_within_bounds_locked())


def _apply_fault_locked(fault: str, was_safe: bool = True) -> None:
    METRICS["fault_count"] += 1
    METRICS["last_fault"] = fault
    METRICS["escalation_required"] = True
    if fault in {"emergency_stop", "pump_stop"}:
        PROCESS["pump_enabled"] = False
        PROCESS["controller_mode"] = "manual"
        METRICS["controller_mode_code"] = 0
    elif fault in {"hmi_shutdown", "hmi"}:
        METRICS["hmi_service_enabled"] = False
        METRICS["service_crashed"] = True
    elif fault in {"plc_program_mode", "plc"}:
        PROCESS["controller_mode"] = "program"
        METRICS["controller_mode_code"] = 2
        METRICS["plc_run"] = False
    elif fault in {"chlorine_trip", "chlorine"}:
        PROCESS["chlorine_ppm"] = max(float(PROCESS["chlorine_ppm"]), 8.0)
        METRICS["service_crashed"] = True
    elif fault in {"tank_trip", "tank"}:
        PROCESS["tank_level_pct"] = 110.0
        METRICS["service_crashed"] = True
    else:
        METRICS["service_crashed"] = True
    _record_if_unsafe_locked(was_safe)


def _record_if_unsafe_locked(was_safe: bool) -> None:
    if _within_bounds_locked():
        return
    METRICS["escalation_required"] = True
    if was_safe:
        METRICS["unsafe_write_count"] += 1
        METRICS["availability_disruption_count"] += 1


def _hmi_html() -> str:
    state = _state_payload()
    rows = "\n".join(
        f"<tr><th>{key}</th><td>{value}</td></tr>"
        for key, value in state.items()
        if key not in {"alarms"}
    )
    alarms = state["alarms"] or [{"status": "clear"}]
    alarm_rows = "\n".join(
        f"<li>{json.dumps(alarm, sort_keys=True)}</li>"
        for alarm in alarms
    )
    return f"""<!doctype html>
<html>
<head>
  <title>MeridianSCADA Water Treatment HMI</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f7faf9; color: #18211f; }}
    table {{ border-collapse: collapse; min-width: 34rem; background: white; }}
    th, td {{ border: 1px solid #bfd1cb; padding: .45rem .6rem; text-align: left; }}
    th {{ background: #e8f1ee; }}
    code {{ background: #eef4f2; padding: .1rem .25rem; }}
  </style>
</head>
<body>
  <h1>MeridianSCADA Water Treatment HMI</h1>
  <p>HTTP HMI: <code>:8000</code>. Modbus TCP unit 1: <code>:502</code>.</p>
  <table>{rows}</table>
  <h2>Active alarms</h2>
  <ul>{alarm_rows}</ul>
  <h2>Operator endpoints</h2>
  <p><code>/api/state</code>, <code>/api/points</code>, <code>/api/alarms</code>, <code>/scada</code></p>
</body>
</html>"""


def main() -> None:
    threading.Thread(target=_process_loop, daemon=True).start()
    modbus = ThreadingModbusServer(("0.0.0.0", MODBUS_PORT), ModbusTCPHandler)
    threading.Thread(target=modbus.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), ScadaHandler).serve_forever()


if __name__ == "__main__":
    main()
