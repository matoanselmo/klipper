# 🐾 Mimi3D

Printer notes, logbook and AI context for **Mimi3D**, a custom Klipper bed-slinger with CAN bus, dual belted Z and input shaping. The live config is backed up here by [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup).

> **For AI assistants:** this README is the source of truth for Mimi3D, a custom Klipper bed-slinger.
> Read it fully before answering. The live config is in `printer_data/config/` of this repo
> (backed up automatically every 4 hours and on boot). If this file and the config disagree,
> the config wins, and point out the mismatch so this file can be updated.
> Sections marked **❓ Unconfirmed** are guesses or stale info waiting for the owner to verify.

**Last reviewed:** 2026-10-12

---

## 1. Ground rules (read before suggesting changes)

- **Never turn Z off.** Z is belt-driven, so the gantry drops when unpowered. Don't add `SET_STEPPER_ENABLE STEPPER=stepper_z* ENABLE=0`, and never use `M84.1` inside macros.
- **Don't change speeds, accelerations, kinematics or `rotation_distance`** unless explicitly asked.
- **Never hand-edit the `SAVE_CONFIG` block** at the bottom of `printer.cfg`. Suggest the calibration command plus `SAVE_CONFIG` instead.
- **Explain the risk first** for anything that can move hardware: endstops, directions, currents, homing, `z_tilt` or probe positions.
- **`mainsail.cfg` is read-only** (symlink to `~/mainsail-config`). Customise PAUSE / RESUME / CANCEL only through `_CLIENT_VARIABLE` in `macros.cfg`.
- **Leave `moonraker.conf` alone** unless asked.
- **Don't restart services yourself.** A restart can kill a running print. The owner restarts with `FIRMWARE_RESTART` / `RESTART` in Mainsail.
- The bed heater on `PC6` drives an **external MOSFET** on purpose. Don't flag it.
- The probe is a **BLTouch clone (CR-Touch type)**. Don't enable `probe_with_touch_mode` or `stow_on_each_sample: False`.
- The owner likes **quiet** motors. X, Y and Z run in StealthChop on purpose.
- **Mind the DP5's shared DIAG pins.** The Y endstop is on PD2 (Z-STOP port, also D2's DIAG) and the runout sensor on PB3 (Y-STOP port, also D1's DIAG). Only X's DIAG jumper is installed.
- CAN errors (`Lost communication`, `bus_state=off`): **check the CAN cable first** before blaming the config.

**This repo:** Klipper-Backup deletes anything in the repo that isn't in its backup paths, **except `README.md`**. So all notes live in this one file. Don't add other files at the repo root from GitHub; put them on the Pi inside a backed-up folder instead.

**Editing style:** keep the `# ---------------- NAME ----------------` section headers, 4-space indents in macros (no tabs), and the `ebb:` prefix on toolhead pins. After an edit, check `~/printer_data/logs/klippy.log` for `Config error`.

---

## 2. Quick facts

| | |
|---|---|
| Name | Mimi3D |
| Type | Custom cartesian bed-slinger, dual Z with `z_tilt` |
| Firmware | Klipper + Moonraker, Mainsail UI |
| Slicer | OrcaSlicer |
| Host user | `ruggy` (services: `klipper.service`, `moonraker.service`) |
| Main board | Mellow Fly DP5 (STM32F072), CAN bridge |
| Toolhead board | BTT EBB42 V1.2 (STM32G0B1), CAN @ 1 Mbit |
| Bed accelerometer | BTT S2DW (RP2040 + LIS2DW), USB |
| Travel X / Y / Z | -5 to 185 / -50 to 180 / -4 to 150 mm |
| Nozzle / filament | 0.4 mm / 1.75 mm |
| Hotend | TZ E3 V2 |
| Extruder | BMG clone, Bowden, geared 50:17 |
| Probe | BLTouch clone, offset X -42, Y 0 |
| Bed | 185×180 mm usable, Creality textured PC sheet, max 90 °C |
| Hotend max temp | 300 °C |

---

## 3. Electronics

### Mellow Fly DP5 (`mcu`)
CAN uuid `efd592e09dd8`. Acts as the USB-to-CAN bridge. Temp sensor name: `dp5_mcu`.

Full pinout from Mellow's pin diagram. Driver slots are numbered D0 to D4 from right to left as seen in that diagram (D0 is next to the power input).

**Driver slots**

| Slot | EN | DIR | STEP | UART | DIAG | Mimi uses it for |
|---|---|---|---|---|---|---|
| D0 | PC2 | PC14 | PC15 | PC13 | PB4 | X (sensorless, DIAG jumper **on**) |
| D1 | PA2 | PA0 | PA1 | PC3 | PB3 | Y (DIAG jumper **off**, PB3 is the runout sensor) |
| D2 | PA6 | PA4 | PA5 | PA3 | PD2 | Z (DIAG jumper **off**, PD2 is the Y endstop) |
| D3 | PB0 | PC4 | PC5 | PA7 | PB5 | Z1 |
| D4 | PB11 | PB2 | PB10 | PB1 | NC | **free**, reserved for 2WD Y |

⚠️ Each DIAG pin is shared with an endstop or header pin. A driver's DIAG jumper only goes on when that driver uses sensorless homing, otherwise it fights whatever else is on the pin.

**Power and heaters**

| Terminal | Pin | Mimi uses it for |
|---|---|---|
| POWER | n/a | PSU input |
| PC6 | PC6 | Bed heater, drives an external MOSFET |
| PC7 | PC7 | free |

**Thermistors**

| Label | Pin | Mimi uses it for |
|---|---|---|
| BED-Temp | PC0 | Bed thermistor (Generic 3950) |
| E-Temp | PC1 | free (a dryer air sensor lived here briefly in Oct 2026) |

**Fans**

| Label | Pin | Mimi uses it for |
|---|---|---|
| FAN0 | PC8 | Case light (PWM) |
| FAN1 | PC9 | Controller fan |
| VCC | n/a | Always-on power header |

**Endstops** (each is signal / GND / 5V)

| Label | Pin | Mimi uses it for |
|---|---|---|
| X-STOP | PB4 | nothing plugged in (X is sensorless, PB4 is X's DIAG) |
| Y-STOP | PB3 | Filament runout switch (`^PB3`) |
| Z-STOP | PD2 | **Y endstop** (`^!PD2`) |

**Expansion headers**

| Header | Row 1 | Row 2 |
|---|---|---|
| EXP1 | PA15, PA14, PA13, NC, 5V | NC, PC11, PC10, NC, GND |
| EXP2 | PB13, PB12, PB15, RST, NC | PB14, PC12, PB6, **PB7**, GND |

PB7 on EXP2 drives the neopixel strip `drivers` (25 LEDs, GRB).

**Other headers**

| Header | Pins | Notes |
|---|---|---|
| CAN | 5V, GND, CAN-L, CAN-H | 120R termination jumper next to it |
| Probe / servo style | PB5, GND, PA8, 5V, GND | PB5 is shared with D3's DIAG |
| UART | PA10, PA9, GND, 5V | |
| USB-C | | Host connection (USB-to-CAN bridge) |

### BTT EBB42 V1.2 (`ebb`)
CAN uuid `69f9e88e88cc`, CAN at 1 Mbit. Mounted upright on the back of the toolhead, USB-C up. Temp sensor name: `ebb_mcu`. It's a V1.2 because the heater is on PB13 (V1.1 boards use PA2).

**Onboard parts**

| Part | Pins | Mimi uses it for |
|---|---|---|
| TMC2209 | EN PD2, STEP PD0, DIR PD1, UART PA15 | Extruder |
| ADXL345 (SPI2) | CS PB12, SCLK PB10, MISO PB2, MOSI PB11 | X resonance (software SPI in config) |
| MAX31865 (SPI1) | CS PA4, SCLK PA5, MISO PA6, MOSI PA7 | not used (for PT100 / PT1000) |
| CAN | TX PB1, RX PB0 | Link to the DP5 |
| USB | DP PA12, DM PA11 | Flashing only |

**Connectors**

| Connector | Pins | Mimi uses it for |
|---|---|---|
| Hotend 0 | Heater PB13 (V1.2) / PA2 (V1.1), VIN | Hotend heater (`ebb:PB13`) |
| TH0 | PA3, GND | Hotend thermistor (Semitec 104NT) |
| PT100 / PT1000 | via MAX31865 | not used |
| FAN1 | PA0, VIN | Part cooling fan |
| FAN2 | PA1, VIN | Hotend fan |
| Probe | GND, 5V, PB9, GND, PB8 | BLTouch: control PB9, sensor PB8 |
| Endstop | PB7, PB5, PB6, GND, 5V | free |
| I2C | 5V, GND, PB3, PB4 | free |
| RGB | 5V, PD3, GND | free |
| E-Motor | | Extruder motor |
| CAN / power | GND, VIN, CAN-L, CAN-H | Cable to the DP5 |

**PT100 / PT1000 DIP switches** (only matter if the MAX31865 is used)

| Sensor | SW1 | SW2 | SW3 | SW4 |
|---|---|---|---|---|
| 2-wire PT100 | ON | ON | ON | OFF |
| 2-wire PT1000 | ON | ON | OFF | OFF |
| 4-wire PT100 | OFF | OFF | ON | OFF |
| 4-wire PT1000 | OFF | OFF | OFF | OFF |

### BTT S2DW (`btt_lis2dw`)
USB serial `/dev/serial/by-id/usb-Klipper_rp2040_5044340418AE361C-if00`. Stuck flat on the bed, measures Y resonance. Pins gpio9 / 10 / 11 / 8 (cs, sclk, mosi, miso). `axes_map: -y, x, z` (measured 2026-10-11).

### Firmware and source paths
- Klipper source: `~/klipper` (option names: `~/klipper/docs/Config_Reference.md`)
- Bootloader: `~/katapult`
- LED plugin: `~/klipper-led_effect`, symlinked into `klippy/extras`

---

## 4. Motion

| Axis | Motor | Current | Microsteps | Driver mode | Homing |
|---|---|---|---|---|---|
| X | Creality 42-34 (0.84 A rated) | 0.58 A (0.45 A while homing) | 16 | StealthChop | Sensorless, `driver_SGTHRS: 100`, toward -X |
| Y | 17HS8401S (42-48, 1.7 A rated) | 1.2 A | 16 | StealthChop | Physical endstop at -50 |
| Z / Z1 | 42-40 (~1.0 A rated) | 0.70 A run, 0.05 A idle hold | 64, interpolate off | StealthChop | BLTouch virtual endstop |
| Extruder | 1.1 A motor | 0.65 A | 16, interpolate on | SpreadCycle (for pressure advance) | n/a |

- All three axes are belt-driven, `rotation_distance: 40` on X, Y and Z.
- X, Y and Z currents all sit at about 70% of each motor's rating.
- Sense resistor on everything: 0.110.
- Current `[printer]` limits: `max_velocity: 300`, `max_accel: 3000`, `max_z_velocity: 15`, `max_z_accel: 100`.
- Orca sends its own `SET_VELOCITY_LIMIT ACCEL=` during prints.

### Homing (`[homing_override]` in `macros.cfg`)
1. Switches Z to run current, hops Z up 10 mm (fakes Z position if Z isn't homed yet)
2. X: drops to 0.45 A, homes sensorlessly, backs off to X10, restores current
3. Y: homes on the physical endstop
4. Z: moves to X120 Y95, probes, lifts to Z10
5. Parks at X78 Y95

Homing Z alone throws `Home X and Y before homing Z` if X/Y aren't homed.

### Z hold
- `hold_z_at_boot` energises both Z motors 1 s after startup at idle current.
- `M84` / `M18` are overridden: they release X, Y and E only, clear X/Y homing, and drop Z to idle current. `[idle_timeout]`, `PRINT_END`, Mainsail's motors-off button and cancel all go through this.
- `M84.1` is the real all-motors-off. Maintenance only.
- Idle hold current is `variable_idle_current` in `_Z_HOLD` (0.05 A). Raise it if the gantry creeps down.
- The controller fan watches X, Y and E only, since Z is always on.

---

## 5. Extruder and hotend

| Setting | Value |
|---|---|
| Hotend | TZ E3 V2 |
| Extruder | BMG clone (dual drive), Bowden |
| `gear_ratio` | 50:17 |
| `rotation_distance` | 22.678 (calibrated 2026-10-09, was 22.52245) |
| Pressure advance | 0.35 |
| Firmware retraction | 4 mm @ 35 mm/s, unretract 35 mm/s, no extra |
| `min_extrude_temp` | 200 °C |
| `max_extrude_cross_section` | 5 |
| `max_extrude_only_distance` | 800 |
| Hotend PID | Kp 42.293, Ki 10.443, Kd 42.822 |

Retraction is tuned live with `SET_RETRACTION`, so the file values may lag what's actually in use.

---

## 6. Bed, probe and levelling

| Setting | Value |
|---|---|
| Bed thermistor | Generic 3950 |
| Bed PID | Kp 67.670, Ki 1.465, Kd 781.591 |
| Probe offset | X -42, Y 0 |
| Probe `z_offset` | 1.519 (SAVE_CONFIG, 2026-10-09) |
| Mesh area | 5,20 to 127,180 (probe coordinates), 10×10, bicubic |
| Mesh fade | 1 to 10 mm |
| Adaptive mesh | Every print, profile `adaptive`, margin 5 mm |
| Saved full mesh | Profile `default` (don't overwrite it) |
| Z tilt | Motors at (260,45) and (-30,45), probes (20,95) and (185,95), 5 retries, 0.03 mm tolerance |

The `default` mesh shows the bed rising about 0.8 mm from front to back.

---

## 7. Input shaping

Calibrated 2026-10-12 with two chips: ADXL345 on the EBB42 for X, LIS2DW on the bed for Y.

| Axis | Shaper | Frequency |
|---|---|---|
| X | MZV | 66.2 Hz |
| Y | MZV | 45.8 Hz |

`[resonance_tester]` probe point: 90, 50, 20.

---

## 8. Fans, lights and sensors

- **Part fan** (`ebb:PA0`): kick start 0.1 s, off below 15%.
- **Hotend fan** (`ebb:PA1`): 75% power once the hotend passes 50 °C.
- **Controller fan** (`PC9`): 25% while X/Y/E are enabled, off 60 s after.
- **Case light** (`PC8`): dimmable, boots at 50%, off on shutdown.
- **Runout sensor** (`PB3`): pauses the print, 3 s event delay.
- **Temperature sensors:** `dp5_mcu`, `ebb_mcu`.

### LED effects (`leds.cfg`, all named `drivers_*`)

| Effect | Look | When |
|---|---|---|
| `drivers_idle` | Static dim purple | Default / after a print |
| `drivers_loading` | Breathing purple | Homing, probing, meshing |
| `drivers_heating_bed` | Red to yellow by bed temp | Bed heating |
| `drivers_heating_extruder` | Red to yellow by hotend temp | Hotend heating |
| `drivers_progress` | Blue progress bar | Printing |
| `drivers_complete` | Blinking green | Print done (30 s, then idle) |

Switch with `SET_LED_EFFECT EFFECT=<name> REPLACE=1`.

---

## 9. Macros

### `PRINT_START BED_TEMP= EXTRUDER_TEMP= SOAK=`
Defaults: bed 60, extruder 210, soak 120 s.
1. LEDs loading, `G28`, `PREVIEW_PRINT_AREA`
2. Bed heats, nozzle goes to 150 °C, `SMART_PARK`
3. Waits for bed, soaks
4. Re-homes Z, `Z_TILT_ADJUST`
5. Adaptive mesh (profile `adaptive`)
6. `SMART_PARK`, heats nozzle to full temp
7. Drops to Z2, `M_PURGE`

Orca start G-code:
```gcode
PRINT_START BED_TEMP=[first_layer_bed_temperature] EXTRUDER_TEMP=[first_layer_temperature] SOAK=120
```
Needs **label objects** enabled in Orca, otherwise the preview, park and purge fall back to defaults.

### Others

| Macro | Notes |
|---|---|
| `PRINT_END` | Retract 2 mm, lift Z10 (capped), park X100 Y150, heaters and fan off, `M84`, LEDs complete |
| `M_PURGE` | 8×8 mm "M" at 0.28 mm, 4 mm in front of the objects (or left of them, or front edge). Primes 10 mm first. Override with `PURGE_X= PURGE_Y=` |
| `SMART_PARK` | 10 mm in front/left of the objects at Z10, or bed centre with no objects |
| `PREVIEW_PRINT_AREA` | Traces the objects' bounding box at Z10. Optional `Z_HOP= SPEED= MARGIN=` |
| `TEST_SPEED` | Skipped-step test, e.g. `TEST_SPEED SPEED=300 ACCEL=5000 ITERATIONS=10` |
| `_CLIENT_VARIABLE` | Mainsail pause/cancel: park X100 Y150, lift 10, park on cancel, firmware retraction, cancel calls `_ON_CANCEL` |
| `_ON_CANCEL` | `M84` + LEDs idle |

### Idle behaviour
`[idle_timeout]` is 30 s: motors (except Z) release, then `heaters_off_when_idle` turns heaters off 270 s later unless something happened in between.

---

## 10. Camera, timelapse and services

| Service | Details |
|---|---|
| Crowsnest | ustreamer, `/dev/video0`, 1280×720 @ 30 fps, port 8080, manual exposure (`exposure_time_absolute=100`) |
| Moonraker | Port 7125 |
| Timelapse | Output `/srv/timelapses/`, frames `/tmp/timelapse/` |
| Smartlapse | Custom service `~/smartlapse/smartlapse.py` (systemd unit `smartlapse.service`), log `~/printer_data/logs/smartlapse.log`. Source is in this repo under `smartlapse/` |
| Spoolman | Separate server on the LAN, port 7912 |
| Mobileraker | Printer name `Mimi3D`, snapshots on |
| Klipper-Backup | `~/klipper-backup`, pushes this repo every 4 h and on boot |

**Smartlapse** grabs the best frame of every layer (nozzle farthest from the camera, moving slowest) and drops it into the timelapse frame folder. It needs no G-code changes: it streams the camera nonstop and rebuilds the exact toolhead position at each frame's capture time from Klipper's motion history (trapq) over the klippy socket. The camera sits on the right end of the Z gantry looking left (`camera_x: 200`). Latency offset -0.08 s (measured 2026-10-11). Restart the service after editing `smartlapse.conf`.

### Useful paths
- Logs: `~/printer_data/logs/klippy.log`, `moonraker.log`, `smartlapse.log`
- G-code uploads: `~/printer_data/gcodes`
- Mainsail config backups: `~/config-backups` (root-owned tarballs)

### Repo layout
```
README.md              # This file (the only root file Klipper-Backup keeps)
printer_data/config/
├── printer.cfg        # MCUs, steppers, heaters, probe, mesh, shaper
├── macros.cfg         # Homing override, PRINT_START/END, purge, park, Z hold
├── leds.cfg           # Case light and neopixel status effects
├── moonraker.conf     # Moonraker, update manager, Spoolman, timelapse
├── crowsnest.conf     # Webcam streaming
├── smartlapse.conf    # Best-frame-per-layer timelapse
└── mobileraker.conf   # Phone notifications
smartlapse/
├── smartlapse.py      # The smartlapse service
└── smartlapse.service # systemd unit
```

---

## 11. ❓ Open questions

Things that look off or are stale. Answer them here once checked.

- [ ] **Part cooling:** did the fan pin swap on 2026-10-12 fix the weak cooling from the Sept 30 log?
- [ ] **Heated bed:** what was wrong with it back in September, and is it sorted?
- [ ] **Y redesign:** is the C$180 redesign done, or is the motor swap all that happened so far?
- [ ] **Z tensioner:** did the one from the Sept 29 log get installed?

**Answered**
- [x] **`max_velocity: 3000`** was a typo, fixed to 300 on the Pi. (2026-10-12)
- [x] **Y motor:** swapped to a 17HS8401S (1.7 A rated), so 1.2 A is about 70% and fine. (2026-10-12)
- [x] **2WD Y:** on paper only, might not happen. See plans. (2026-10-12)
- [x] **Hotend / extruder:** TZ E3 V2 hotend, BMG clone extruder. (2026-10-12)
- [x] **Z drive:** belts. (2026-10-12)
- [x] **Bed:** 185×180 mm usable (matches X max 185, Y max 180), Creality textured PC sheet. (2026-10-12)

---

## 12. Plans and ideas

- 2WD Y (maybe, on paper only): `stepper_y1` on D4, two 42-40s at about 0.65 A each, full StealthChop.

---

## 13. Change log

From 2026-10-02 on, reconstructed from the backup history, so dates are backup times and can lag the real change by a few hours. Earlier entries come from the engineer's logs (section 16). Newest first. Add new entries at the top.

| Date | Change |
|---|---|
| 2026-10-12 | `max_velocity` typo fixed, 3000 to 300 |
| 2026-10-12 | Printer notes moved into the README (Klipper-Backup deletes other root files). Smartlapse source and systemd unit added to the repo |
| 2026-10-12 | Part fan and hotend fan pins swapped (part fan now `ebb:PA0`), hotend fan capped at 75%, Z removed from controller fan, Z idle hold current 0.35 A to 0.05 A |
| 2026-10-12 | Smartlapse added. BTT S2DW added on the bed. Input shaper calibrated: X MZV 66.2, Y MZV 45.8. PA 0.7 to 0.35. Limits: velocity 600 to 3000, accel 6000 to 3000 |
| 2026-10-11 | Extruder: interpolate on, 0.8 A to 0.65 A, SpreadCycle, `min_extrude_temp` 0 to 200 |
| 2026-10-11 | KAMP removed (replaced by own `SMART_PARK`), new `[homing_override]`, dryer and probe-limits macros removed, old CLAUDE.md removed (folded into this file) |
| 2026-10-10 | Bed max temp 120 to 90, z_tilt probe point 170 to 185 |
| 2026-10-09 | Extruder `rotation_distance` 22.52245 to 22.678. z_offset settled at 1.519 |
| 2026-10-07 | Filament dryer macro added (later removed). Retraction settled at 4 mm @ 35. Z min -2 to -4 |
| 2026-10-06 | Homing refactor, Z needs X/Y homed first |
| 2026-10-05 | X travel -20..170 to -5..185. Mobileraker added |
| 2026-10-04 | `Z_TILT_ADJUST` added to `PRINT_START`, extruder 0.75 to 0.8 A, controller fan tweaks |
| 2026-10-03 | Y current 0.9 to 1.2 A (probably when the 17HS8401S went in), Y full StealthChop |
| 2026-10-02 | KAMP added, `M_PURGE` and `SMART_PARK` in `PRINT_START`, Z re-home after soak. First backup |
| 2026-09-29 | New Z axis part installed |
| 2026-09-26 | Z tilt set up, EBB42 mounted on the toolhead |
| 2026-09-23 | Wiring redone (with Wagos) |

---

## 14. Maintenance log

| Date | What was done | Notes |
|---|---|---|
| | | |

Ideas to track: belt tension, nozzle swaps, lubricating Z, PTFE tube, cleaning the bed, firmware updates (Klipper on DP5 / EBB42 / S2DW need reflashing after big Klipper updates).

---

## 15. Problems and fixes

Keep a short note of every issue so future you (and any AI) can spot patterns.

| Date | Symptom | Cause | Fix |
|---|---|---|---|
| 2026-09-30 | Weak part cooling, cause unknown at the time | ❓ Possibly the part fan and hotend fan pins being swapped in the config | Pins swapped on 2026-10-12 (part fan now `ebb:PA0`). Confirm it helped |
| 2026-09-26 | Y motor not powerful enough | Original 42-34 too weak for the bed | Swapped to a 17HS8401S, run at 1.2 A |
| 2026-09-22 | Couldn't print anything big. Y axis and heated bed were the weak spots | Y motor (see above). ❓ Heated bed cause not recorded | Y redesign started. Bed max temp later set to 90 °C (2026-10-10) |

---

## 16. Engineer's logs

Handwritten logs from before the config backups started, transcribed (spelling tidied up). Year assumed to be 2026. Add new entries at the bottom.

**Sept 22nd**
Printer worked, ish. Can't print anything too big. Thinking of going directly to the Y axis refactor. This is because most of the other axes are working, but the Y and heatbed aren't. Extruder is great btw!

**Sept 23rd**
I'm not entirely sure if I will buy the Z axis part, to focus on the Y axis now. Wiring was redone today. It's great! I might need some extra 14 AWG wire. I love Wagos!

**Sept 26th**
Mimi has been working great! New wiring is flawless, Z tilt is done, EBB is mounted. We're at the Y redesign stage. Around C$180 to buy everything for it. Will do after the first week of Oct.
**Important:** Y axis motor does need to be replaced. It is not powerful enough!

**Sept 29th**
New Z axis part is very good! I continue looking for a Z tensioner and I might have found it! I might need some extra hardware (urgent) but I'm not sure yet. Next step is the Y axis, soon to be done too!

**Sept 30th**
Almost everything goes well BUT part cooling, and I don't know why yet! I might have to change the fan or something.
