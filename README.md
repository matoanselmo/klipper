<div align="center">

# 🐾 Mimi3D

**A heavily tuned Klipper bed-slinger with CAN bus, dual Z, input shaping and a smart timelapse camera.**

![Klipper](https://img.shields.io/badge/firmware-Klipper-B12F35?style=flat-square)
![Mainsail](https://img.shields.io/badge/UI-Mainsail-1F8EB2?style=flat-square)
![Kinematics](https://img.shields.io/badge/kinematics-cartesian-555?style=flat-square)
![CAN bus](https://img.shields.io/badge/toolhead-CAN%20bus-6A4C93?style=flat-square)
![Backups](https://img.shields.io/badge/backups-every%204h-2EA043?style=flat-square)

</div>

---

This repo holds the live configuration for **Mimi3D**. Everything in `printer_data/config` is backed up automatically by [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup), so if something goes sideways you can always roll back to a config that worked.

## ✨ At a glance

| | |
|---|---|
| **Firmware** | Klipper + Moonraker |
| **Interface** | Mainsail, Mobileraker (phone app) |
| **Kinematics** | Cartesian bed-slinger |
| **Travel (X / Y / Z)** | -5 → 185 mm / -50 → 180 mm / -4 → 150 mm |
| **Main MCU** | Mellow Fly DP5 over CAN bus (`mcu`) |
| **Toolhead** | BTT EBB42 over CAN bus (`ebb`) |
| **Nozzle / filament** | 0.4 mm / 1.75 mm |
| **Hotend thermistor** | ATC Semitec 104NT, max 300 °C |
| **Extruder** | Geared 50:17, pressure advance 0.35 |
| **Bed** | Generic 3950 thermistor, max 90 °C |
| **Probe** | BLTouch on the toolhead |
| **Z** | Dual independent Z motors with `Z_TILT_ADJUST` |
| **Input shaper** | X: MZV @ 66.2 Hz · Y: MZV @ 45.8 Hz |
| **Camera** | USB webcam via Crowsnest (1280×720 @ 30 fps) |

## 🔧 Hardware notes

**Motion.** X homes sensorlessly using the TMC2209's StallGuard (with a reduced homing current so it bumps gently), Y uses a physical endstop, and Z homes with the BLTouch. All drivers are TMC2209s running in SpreadCycle.

**Z gantry hold.** Mimi's Z gantry drops when the motors lose power, so Z never gets switched off. `M84` and `M18` are overridden to release only X, Y and the extruder. When idle, the Z motors drop to a quieter hold current and go back to full power before any move. If you *really* need every motor off, use `M84.1`.

**Two accelerometers.** Since the bed moves in Y, resonance testing is split across two chips:
- an **ADXL345** on the EBB42 toolhead board measures X
- a **BTT S2DW (LIS2DW)** stuck to the bed, connected over USB, measures Y

**Lights.** A dimmable case light (boots at 50%) plus a 25-LED neopixel strip on the drivers that changes effect with the printer's state: idle, heating bed, heating hotend, loading, printing progress and complete.

**Filament runout.** A switch sensor pauses the print automatically when filament runs out.

## 🖨️ Print workflow

Set your slicer's start G-code to something like:

```gcode
PRINT_START BED_TEMP=[first_layer_bed_temperature] EXTRUDER_TEMP=[first_layer_temperature] SOAK=120
```

and the end G-code to:

```gcode
PRINT_END
```

Here's what `PRINT_START` does for you:

1. Homes everything and previews the print area
2. Heats the bed while warming the nozzle to a safe 150 °C (no oozing during probing)
3. Parks near the print and **heat soaks** the bed (120 s by default) so it actually settles
4. Re-homes Z after thermal expansion, then runs `Z_TILT_ADJUST`
5. Probes a fresh **adaptive bed mesh** only under the objects being printed (saved to its own `adaptive` profile so the full `default` mesh stays safe)
6. Brings the hotend to full temperature
7. Draws a tiny 8×8 mm **"M" purge** right in front of the parts and starts printing

The LEDs follow along the whole way, so you can tell what Mimi is up to from across the room.

## 🧰 Handy macros

| Macro | What it does |
|---|---|
| `PRINT_START` | Full pre-print routine (see above) |
| `PRINT_END` | Retracts, parks and wraps things up |
| `M_PURGE` | Compact "M" shaped purge line in front of the print area |
| `SMART_PARK` | Parks the head just in front of / left of the print area |
| `PREVIEW_PRINT_AREA` | Traces where the objects will be printed |
| `TEST_SPEED` | Stress-tests speed and acceleration and checks for skipped steps, e.g. `TEST_SPEED SPEED=300 ACCEL=5000 ITERATIONS=10` |
| `M84` / `M18` | Motors off, except Z (keeps the gantry from dropping) |

When Mimi sits idle, the motors release after 30 s and the heaters switch off a few minutes later.

## 📸 Smartlapse

Mimi has a custom **smartlapse** service (`smartlapse.conf`) that watches the camera stream and, for every layer, picks the single best frame: the one where the nozzle is farthest from the camera and moving slowest. Those frames feed straight into the Moonraker timelapse plugin, so you get clean timelapses without the usual "park the head every layer" slowdown.

The camera sits on the right end of the Z gantry looking left, and latency is calibrated to -0.08 s. Restart the smartlapse service after editing its config.

## 📂 What's in here

```
printer_data/config/
├── printer.cfg        # Main config: MCUs, steppers, heaters, probe, mesh, shaper
├── macros.cfg         # Homing override, PRINT_START/END, purge, park, Z hold
├── leds.cfg           # Case light and neopixel status effects
├── moonraker.conf     # Moonraker, update manager, Spoolman, timelapse
├── crowsnest.conf     # Webcam streaming
├── smartlapse.conf    # Best-frame-per-layer timelapse
└── mobileraker.conf   # Phone notifications
```

## 🧩 Software stack

- [Klipper](https://www.klipper3d.org/) firmware
- [Moonraker](https://github.com/Arksine/moonraker) API server
- [Mainsail](https://docs.mainsail.xyz/) web interface
- [Klipper LED Effect](https://github.com/julianschill/klipper-led_effect) for the status lights
- [Crowsnest](https://github.com/mainsail-crew/crowsnest) for the webcam
- [Moonraker Timelapse](https://github.com/mainsail-crew/moonraker-timelapse) + custom smartlapse
- [Spoolman](https://github.com/Donkie/Spoolman) for filament tracking
- [Mobileraker](https://github.com/Clon1998/mobileraker) for notifications on the go
- [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup) keeping this repo up to date

## ⚠️ Heads up

The bottom of `printer.cfg` holds the auto-generated `SAVE_CONFIG` block (PID tunes, bed mesh, input shaper, probe Z offset). Don't hand edit it. Run the calibration again and use `SAVE_CONFIG` instead.

---

<div align="center">

Made with ❤️ (and a lot of test prints) for Mimi.

</div>
