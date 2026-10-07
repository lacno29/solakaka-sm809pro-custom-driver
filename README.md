# SM809 Pro App

A lightweight, feature-rich custom desktop driver and configuration suite for the **SOLAKAKA SM809 Pro** wireless MMO gaming mouse. Built on a fully reverse-engineered HID protocol, this application provides a modern, bloat-free alternative to the official software with powerful capabilities—including seamless **per-application profile auto-switching**.

---

## What It Does

The official vendor software is clunky and lacks automatic game/application detection. This app replaces it with a clean, responsive desktop utility that gives you complete control over your hardware:

### 🎯 Per-Application Profile Auto-Switching
- **Automatic Process Detection**: Watches your active foreground window and instantly switches profiles based on the executable name, full file path, or window title.
- **Priority-Based Rules**: Reorder profiles to set matching priority when multiple rules apply.
- **Base Profile Fallback**: Automatically reverts back to your preferred default profile when no application-specific rule matches.

### 🖱️ 16-Button Remapping
- **Full Layout Customization**: Remap every single physical button—including the 12-button side thumb grid, DPI toggles, and top buttons.
- **Flexible Action Library**: Assign standard mouse clicks, keyboard keys, multimedia functions, web browser navigation, DPI adjustment, and macro playback.
- **Host-Side "Run App"**: Bind any button to launch an external executable, script, or URL directly from the host system without requiring global keyboard hooks.

### ⌨️ Built-in Macro Editor
- **Full Sequence Recording & Editing**: Record key presses, mouse clicks, and exact delays.
- **Timing Control**: Configure fixed delays, recorded delays, or minimal latencies.
- **Flexible Playback Modes**: Set cycle counts, continuous loop while held, or toggle repeat on/off.
- **On-Device Storage**: Uploads macros directly to on-board mouse memory.

### ⚡ Sensor & Performance Tuning
- **Adjustable DPI Stages**: Configure up to 8 DPI stages (ranging from 100 to 24,000 DPI in 100 DPI increments) with custom indicator colors for each level.
- **Polling Rate**: Toggle between 125 Hz, 250 Hz, 500 Hz, and 1000 Hz reporting rates.
- **Lift-Off Distance (LOD)**: Switch between 1 mm and 2 mm lift-off thresholds.
- **Advanced Sensor Flags**: Toggle PixArt PAW3311 sensor features including Motion Sync, Angle Snapping, and Ripple Control.
- **Power Management**: Configurable idle sleep timeout to preserve battery life in wireless mode.

### 💡 RGB Lighting Customization
- **Lighting Effects**: Choose between multiple lighting modes including Streaming (Neon), Breathing, Single-Color Static, Stars, and Off.
- **Fine Control**: Adjust brightness levels, animation speeds, and RGB color palettes.

### 📊 Live Telemetry & On-Screen Display (HUD)
- **Real-Time Status Bar**: Displays live battery percentage, charging state, connection mode (2.4 GHz wireless vs. USB wired), and current DPI stage.
- **Floating Overlay HUD**: An optional on-screen display that briefly flashes current DPI, polling rate, or profile changes so you never lose track during gameplay. Configurable screen position, opacity, and size.

### 📁 Profile Management & `.psf` Importer
- **Portable JSON Storage**: Profiles and macros are stored locally in human-readable JSON files (`config/profiles.json` and `config/macros.json`).
- **Official Profile Migration**: Import legacy `.psf` profile files from the official vendor utility with automatic decoding of keymaps, DPI stages, lighting, and macro events.

### 🪟 Modern UI & System Tray Integration
- Clean dark theme designed for fast navigation without flashy bloat.
- Minimizes quietly to the Windows system tray.
- Single-instance enforcement with seamless handoff when relaunched.

---

## ⏱️ Profile Switching & Hardware Timing (Disclaimer & Tip)

Because the SM809 Pro's microcontroller is stateful and communicates over USB HID Feature reports:
- **Mandatory Hardware Settle Delay**: The mouse firmware requires a mandatory ~60 ms settle delay after every HID feature write (`CMD_DELAY = 60ms`) to prevent the microcontroller from wedging. Macro uploads additionally require a 120 ms delay between data chunks (`MACRO_CHUNK_DELAY = 120ms`).
- **Smart Diffing**: To make switching as fast as possible, the driver diffs incoming profiles against what is currently applied on the hardware. If an auto-switch only changes DPI or lighting, only those specific packets are sent (taking a fraction of a second).
- **Why Some Profile Switches Take Longer**: If a profile changes many sections at once—such as all 16 button remappings, lighting, sensor flags, polling rate, and complex multi-key macros—up to 7+ command packets plus chunked macro data must be written sequentially across the HID interface. This can cause a brief delay of around ~0.5s to 1.5s before the device completes writing all changes.
- **Alt-Tab Debounce**: During automatic profile switching, a 200 ms stability debounce (with a 200 ms polling loop) is deliberately enforced so rapid Alt-Tabbing across open windows does not flood the mouse hardware with back-to-back writes.

> [!TIP]
> **Enable the On-Screen Overlay HUD for Visual Confirmation:**  
> In the system tray menu, open **Overlay settings…** and enable the on-screen display. When a profile switch begins, the overlay immediately displays `"Switching to [Profile Name]"` while the packets are in transit, and then flashes the confirmed profile card once the mouse firmware has completely finished applying the changes.

---

## Hardware Compatibility

- **Device**: SOLAKAKA SM809 Pro MMO Gaming Mouse
- **Sensor**: PixArt PAW3311 (100–24,000 DPI)
- **Connections**:
  - **2.4 GHz Wireless** (USB Dongle, VID `0x04F3`, PID `0x026F`)
  - **USB Wired** (USB-C Cable, VID `0x04F3`, PID `0x026E`)
  - *(Note: Bluetooth mode does not expose vendor HID configuration collections; use 2.4GHz or wired to configure settings).*

---

## Getting Started

### Prerequisites

- Python 3.10+ (tested on Windows)
- Required packages:
  ```bash
  pip install PySide6 hidapi
  ```

### Running from Source

```bash
python run_app.py
```

### Running Tests

Run the test suite offline (no mouse hardware required):

```bash
# Offline framing and protocol encoding tests (37 tests)
python tests/test_offline.py

# Headless GUI, profile store, .psf import, and auto-switch tests
python tests/test_gui_headless.py
```

---

## Building a Standalone Executable (Windows)

To package the application into a standalone `.exe` without needing a terminal or Python installation:

```bash
pip install pyinstaller
build_exe.bat
# or manually:
python -m PyInstaller --noconfirm SM809Pro.spec
```

The output will be placed in `dist\SM809Pro.exe`. It runs portably and stores user profiles in a `config/` directory placed beside the executable.

---

## Project Structure

```
SM809ProApp/
├── sm809pro/             # Core driver package (reverse-engineered protocol & HID I/O)
│   ├── protocol.py       # HID packet definitions, report IDs, command opcodes, checksums
│   ├── actions.py        # Button action mappings, permutations, and factory defaults
│   ├── device.py         # Persistent HID session manager, commands, and device discovery
│   ├── macros.py         # Macro encoding and device chunked upload logic
│   ├── status.py         # Background status listener (DPI updates, heartbeat, battery)
│   └── defaults.py       # Single source of truth for factory default configuration
├── app/                  # PySide6 GUI and automation engine
│   ├── controller.py     # Background device controller thread with Qt signals
│   ├── main_window.py    # Main window shell, navigation rail, and system tray logic
│   ├── autoswitch.py     # Foreground window monitor and profile auto-switch rules
│   ├── profile_store.py  # JSON profile serializer and persistence manager
│   ├── psf_import.py     # Parser for official OEM .psf profiles
│   ├── theme.py          # Dark stylesheet styling ("Precision Instrument" theme)
│   ├── panels/           # UI panels (Buttons, Macros, DPI, Lighting, Performance, Auto-Switch, Profiles)
│   └── widgets/          # Reusable UI components (Action picker, color selector, overlay HUD)
├── config/               # Default profile and macro configurations (profiles.json, macros.json)
├── tests/                # Automated offline and offscreen headless test suites
├── build_exe.bat         # Windows build script for PyInstaller
├── SM809Pro.spec         # PyInstaller specification file
└── run_app.py            # Main application entry point
```
