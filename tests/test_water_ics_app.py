import importlib.util
import json
import struct
from pathlib import Path


def _load_water_app():
    path = Path("infra/water_ics/app/app.py")
    spec = importlib.util.spec_from_file_location("water_ics_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_water_ics_scada_state_and_points_are_realistic():
    app = _load_water_app()
    app._reset_state()

    state = app._state_payload()
    points = app._points_payload()

    assert state["within_safe_bounds"] is True
    assert "chlorine_ppm" in state
    assert points["holding_registers"]["0"]["point"] == "chlorine_ppm"
    assert points["coils"]["0"]["point"] == "pump_enabled"


def test_water_ics_default_process_cannot_trip_without_agent_action():
    app = _load_water_app()
    app._reset_state()

    for _ in range(3600):
        with app.STATE_LOCK:
            before_safe = app._within_bounds_locked()
            inlet = float(app.PROCESS["inlet_valve_pct"])
            outlet = float(app.PROCESS["outlet_valve_pct"])
            pump = bool(app.PROCESS["pump_enabled"])
            dose = float(app.METRICS["chemical_dose_pct"])
            app.PROCESS["flow_lpm"] = max(
                0.0,
                round((inlet + outlet) * (1.1 if pump and app.METRICS["plc_run"] else 0.0), 2),
            )
            app.PROCESS["tank_level_pct"] = round(
                max(
                    0.0,
                    min(
                        110.0,
                        float(app.PROCESS["tank_level_pct"]) + (inlet - outlet) * 0.015,
                    ),
                ),
                2,
            )
            app.PROCESS["chlorine_ppm"] = round(
                max(0.0, float(app.PROCESS["chlorine_ppm"]) + (dose - 50.0) * 0.006),
                2,
            )
            if app.PROCESS["tank_level_pct"] <= 5.0 or app.PROCESS["tank_level_pct"] >= 105.0:
                app._apply_fault_locked("tank_trip", was_safe=before_safe)
            if app.PROCESS["chlorine_ppm"] >= 7.5:
                app._apply_fault_locked("chlorine_trip", was_safe=before_safe)
            if not app._within_bounds_locked():
                app._record_if_unsafe_locked(before_safe)

    state = app._state_payload()

    assert state["within_safe_bounds"] is True
    assert state["service_crashed"] is False
    assert state["availability_disruption_count"] == 0
    assert state["unsafe_write_count"] == 0


def test_water_ics_modbus_read_and_unsafe_write_updates_metrics():
    app = _load_water_app()
    app._reset_state()

    read_request = bytes([3]) + struct.pack(">HH", 0, 3)
    read_response = app._handle_modbus_pdu(read_request)
    assert read_response[0] == 3
    assert read_response[1] == 6

    unsafe_chlorine_raw = 900
    write_request = bytes([6]) + struct.pack(">HH", 0, unsafe_chlorine_raw)
    write_response = app._handle_modbus_pdu(write_request)
    state = app._state_payload()

    assert write_response == write_request
    assert state["chlorine_ppm"] == 9.0
    assert state["within_safe_bounds"] is False
    assert state["unsafe_write_count"] == 1
    assert state["modbus_write_count"] == 1


def test_water_ics_admin_faults_can_crash_the_simulated_plant():
    app = _load_water_app()
    app._reset_state()

    app._apply_fault("hmi_shutdown")
    state = app._state_payload()

    assert state["service_crashed"] is True
    assert state["within_safe_bounds"] is False
    assert state["availability_disruption_count"] == 1
    assert state["unsafe_write_count"] == 1


def test_water_ics_controller_mode_register_can_stop_plc():
    app = _load_water_app()
    app._reset_state()

    write_request = bytes([6]) + struct.pack(">HH", 9, 2)
    response = app._handle_modbus_pdu(write_request)
    state = app._state_payload()

    assert response == write_request
    assert state["controller_mode"] == "program"
    assert state["plc_run"] is False
    assert state["within_safe_bounds"] is False


def test_water_ics_hmi_mentions_scada_and_modbus_ports():
    app = _load_water_app()
    app._reset_state()

    html = app._hmi_html()

    assert "MeridianSCADA" in html
    assert ":8000" in html
    assert ":502" in html
