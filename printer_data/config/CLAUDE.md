# Klipper printer config

Klipper + Moonraker + Mainsail config for a custom cartesian printer. Everything runs on this host (user `ruggy`); services are `klipper.service` and `moonraker.service`.

## Files

| File | Editable | Purpose |
|---|---|---|
| `printer.cfg` | yes | Hardware: MCUs, steppers/TMC, extruder, bed, fans, probe, z_tilt, bed_mesh |
| `macros.cfg` | yes | `PRINT_START`, `PRINT_END`, `PREVIEW_PRINT_AREA`, Z-hold loop |
| `leds.cfg` | yes | Neopixel strip `drivers` + `led_effect` definitions |
| `probe_offsets.cfg` | yes | `GET_PROBE_LIMITS` macro (prints probe offsets and reachable probe area) + `[respond]` |
| `mainsail.cfg` | **no** | Symlink to `~/mainsail-config/mainsail.cfg` (managed by update_manager) |
| `moonraker.conf` | **no** | System/Moonraker config, leave alone unless asked |
| `.moonraker.conf.bkp` | **no** | Auto-generated backup |

Include chain: `printer.cfg` includes `mainsail.cfg`, `macros.cfg`, `leds.cfg` and `probe_offsets.cfg`. Nothing else includes files.

Mainsail's PAUSE/CANCEL_PRINT/RESUME live in the read-only `mainsail.cfg`. Customise them only through `_CLIENT_VARIABLE` in `macros.cfg`:
- It parks at X100 Y150 with a 10 mm lift, parks on cancel too, and uses firmware retraction.
- `user_cancel_macro` calls `_ON_CANCEL`, which runs the Z-safe `M84` and switches the LEDs to idle.
- Mainsail's `on_error_gcode` also goes through CANCEL_PRINT.

`[firmware_retraction]` (G10/G11) is in `printer.cfg`. The user tunes it live with `SET_RETRACTION`; the values in the file were copied from the user's slicer: 0.8 mm at 30/30 mm/s, no extra on restart.

## Hardware

- **Main MCU** `mcu` is a **Mellow Fly-DP5** (stm32f072, called `dp5` in the temp sensor), CAN uuid `efd592e09dd8`. It acts as the USB-to-CAN bridge.
  - Drivers: D0 = X, D1 = Y, D2 = Z, D3 = Z1. **D4 is free** (EN PB11, STEP PB10, DIR PB2, UART PB1) and reserved for a planned 2WD Y (`stepper_y1`, two 42-40s at about 0.65 A each, full StealthChop).
  - The bed heater uses PC6 (the HEAT0 output) to drive an **external MOSFET**. That's intentional and fine, so don't flag it.
  - It also runs the controller fan and the neopixels (PB7).
- **Toolhead** `ebb` (EBB board, stm32g0b1), CAN uuid `69f9e88e88cc`, CAN at 1 Mbit. Drives extruder, hotend heater/thermistor, part + hotend fans, BLTouch, ADXL345 (software SPI).
- Firmware sources: `~/klipper`, `~/katapult` (bootloader). The `led_effect` plugin is in `~/klipper-led_effect`, symlinked into `klippy/extras`.
- Kinematics: cartesian, dual Z (`stepper_z` + `stepper_z1`) levelled with `[z_tilt]`.
- X uses sensorless homing (TMC2209 virtual endstop, `driver_SGTHRS: 100`). Y uses a physical endstop at `-50`. Z uses the BLTouch virtual endstop.
- Travel: X -20–175 (X endstop at -20), Y -50–180, Z -2–150.
- Probe (BLTouch) offset: x -42, y 0. Mesh bounds (5–132, 20–180) are in **probe** coordinates, so they account for this offset. `GET_PROBE_LIMITS` prints the reachable probe area.
- Extruder: **bowden** with a 1.1 A motor. `gear_ratio: 50:17` + `rotation_distance: 22.52245` are calibrated, so don't touch them. Semitec 104NT thermistor.
- Motors (currents are about 70% of the rating):
  - X: Creality 42-34 (0.84 A), run at 0.58 A.
  - Y: 42-34, run at 0.9 A (above its rating; the user's deliberate choice). It had problems at 0.58 A and 0.7 A with 6000 accel, then ran at 0.8 A before the user raised it to 0.9 A. The user plans to swap in a 42-40, which would fix this properly.
  - Z and Z1: 42-40 (~1.0 A), run at 0.70 A, 64 microsteps, interpolate off.
  - Extruder: run at 0.75 A.
- The user wants **quiet** motors. X and Z stay in StealthChop (`stealthchop_threshold: 999999`). Y is in hybrid mode (`stealthchop_threshold: 150`): StealthChop below 150 mm/s, SpreadCycle above, because it lacked torque at 6000 accel. The user set 0.9 A + threshold 150 deliberately, so don't change it until the 2WD upgrade. The extruder stays in SpreadCycle for pressure advance.
- **Never change** speeds, accelerations, kinematics or rotation_distance unless explicitly asked.
- `max_accel` is 6000 (`max_velocity` 300), matching what the slicer (Orca) sends via `SET_VELOCITY_LIMIT ACCEL=` during prints. The user is happy with 6000. If X layer shifts appear, first raise X run_current (up to about 0.70 A); Y is already above its rating, so the fix there is the 42-40 / 2WD upgrade.
- The probe is a BLTouch **clone** (CR-Touch type), so don't enable `probe_with_touch_mode` / `stow_on_each_sample: False`.
- The toolhead CAN board is now mounted (upright on the back of the toolhead, USB-C up; ADXL `axes_map: x, z, -y`).
  - Input shaper: X is calibrated (EI 60.6 Hz, in the SAVE_CONFIG block). Y is unshaped because the toolhead chip can't measure a bed-slinger's Y; it waits for a bed-mounted accelerometer (BTT S2DW) that comes with the Y redesign.
  - If `Lost communication` or CAN `bus_state=off` errors appear, check the CAN cable first before blaming the config.
- `[homing_override]` replaces `safe_z_home` (Klipper can't run both). It does the Z hop, homes X sensorlessly at 0.45 A with a 2 s pause, homes Y (physical endstop, `homing_speed: 80`), then homes Z at 100,95. The post-home travel moves run at F6000 / F12000. The user confirmed that `driver_SGTHRS: 100` homes reliably at 0.45 A, so retune only if X stops short or grinds.

## SAVE_CONFIG block

The part of `printer.cfg` below `#*# <---- SAVE_CONFIG ---->` is written by Klipper. It holds the extruder PID, the `default` bed mesh and `[input_shaper]` (X only). The BLTouch `z_offset` is currently `0` in the main `[bltouch]` section, not in this block; a `PROBE_CALIBRATE` + `SAVE_CONFIG` would add it here. **Never hand-edit it.** Values there override the same keys above (e.g. the commented `#control: pid` extruder lines). To change these values, run the calibration command and then `SAVE_CONFIG`, or tell the user which commands to run.

## Macros and behaviour to know

- `PRINT_START BED_TEMP= EXTRUDER_TEMP= SOAK=`: homes if needed, runs Z_TILT_ADJUST, traces the object bounding box (needs slicer "label objects"), heats and soaks the bed (default 120 s), sets the nozzle to 150 °C, runs a fresh adaptive mesh under the objects (profile `adaptive`, so the saved `default` mesh is kept), heats the nozzle, then draws a purge line at X20. LED effects change at each stage.
- `PRINT_END`: retracts, lifts Z by 10 mm (capped at max), parks at X100 Y150, turns off heaters and the fan, calls the Z-safe `M84` and switches LEDs to complete. After 30 s they return to idle.
- **Z hold:** the Z gantry drops when unpowered, so Z must never be turned off.
  - `hold_z_at_boot` enables `stepper_z` and `stepper_z1` 1 s after startup.
  - `M84` and `M18` are overridden in `macros.cfg` to release only X, Y and E, and to clear X/Y homing.
  - `[idle_timeout]` and `PRINT_END` go through `M84`.
  - `M84.1` is the real all-motors-off, for maintenance only.
  - Never add plain `SET_STEPPER_ENABLE ... ENABLE=0` for Z, and never use `M84.1` in macros.
  - The old 5 s re-enable loop was removed. It only covered `stepper_z` and flushed the motion queue during prints.
- LED effects are all named `drivers_*`. Switch between them with `SET_LED_EFFECT EFFECT=... REPLACE=1`.

## Editing conventions

- Keep the existing section-header comment style (`# ---------------- NAME ----------------`).
- Macro bodies use 4-space indentation. Some lines in `macros.cfg` currently use tabs; Klipper accepts both, but use spaces for new lines.
- Pin names on the toolhead need the `ebb:` prefix.
- After editing, the user restarts Klipper (`FIRMWARE_RESTART` / `RESTART` in Mainsail). To validate, check `~/printer_data/logs/klippy.log` for `Config error` after a restart. Don't restart services yourself unless asked, because it can interrupt a print.
- Before any edit that could move hardware (endstops, directions, rotation_distance, currents, homing, z_tilt/probe positions), explain the risk to the user.
- Mainsail has config backups in `~/config-backups` (root-owned tarballs). This directory is **not** a git repo, so make a copy before large rewrites.

## Useful paths

- Logs: `~/printer_data/logs/klippy.log`, `moonraker.log`
- G-code uploads: `~/printer_data/gcodes`
- Klipper source (for checking option names): `~/klipper/klippy/extras/`, `~/klipper/docs/Config_Reference.md`
