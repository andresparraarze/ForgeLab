# ForgeLab examples

Reference ForgeLab documents for every domain. Each `.forge.json` validates
cleanly with `validate_document` and exports to its native format with
`export_document`; every `meta.description` explains what the document shows and
why it's a good reference. Use them as few-shot examples when authoring new
documents — start from the one closest to your task and adapt it.

## Canonical examples

| Example | Domain | Exports to | Demonstrates |
| --- | --- | --- | --- |
| [`hardware/blinky_led.forge.json`](hardware/blinky_led.forge.json) | hardware | KiCad `.kicad_pcb` | The hardware "hello world": a power header, 330R resistor and LED in series between +5V and GND on a 20×20mm board. 3 components, 3 nets — the minimal complete board. |
| [`hardware/arduino_uno.forge.json`](hardware/arduino_uno.forge.json) | hardware | KiCad `.kicad_pcb` | A complete Arduino Uno clone: ATmega328P (TQFP-32) and CH340G (SOIC-16) with **real pad geometry from `calculate_pad_positions`**, crystal + load caps, AMS1117-3.3 regulator, analog/digital/power/ICSP headers, power + TX/RX LEDs, reset button, MCU decoupling, on the 68.58×53.34mm outline. Reference for a real multi-IC board with dozens of named nets. |
| [`mechanical/motor_mount.forge.json`](mechanical/motor_mount.forge.json) | mechanical | FreeCAD `.FCStd` | The canonical mechanical example: a NEMA17 mount plate (100×60×3mm) with a 38mm central bore, four M3 holes on the 31mm bolt pattern, and four M4 corner holes. Shows the part → body → sketch → pad/pocket tree. Passes the sanity checks with no warnings. |
| [`mechanical/enclosure.forge.json`](mechanical/enclosure.forge.json) | mechanical | FreeCAD `.FCStd` | A PCB enclosure box (120×80×40mm, 2mm walls, open top) with four M3 mounting bosses. Combines additive + subtractive features: a solid block, a cavity pocket leaving floor and walls, raised bosses, and pilot holes. No warnings. |
| [`threed/space_station.forge.json`](threed/space_station.forge.json) | threed | glTF `.gltf` | A sci-fi space station (rotating ring, hub + spokes, docking port, dual solar arrays, comm dish), authored Y-up and confirmed in Blender. Reference for a large multi-mesh scene sharing a material palette. |
| [`threed/torii_gate.forge.json`](threed/torii_gate.forge.json) | threed | glTF `.gltf` | A Japanese torii gate (pillars, kasagi + shimaki lintel with black caps, nuki crossbeam, central strut) in vermilion red, authored Y-up. A simple, iconic scene built from boxes and cylinders with two materials. |

## Few-shot fixtures

Smaller documents wired into the SDK prompts (`forgelab.sdk.system_prompt` /
`few_shot`) and used as test fixtures. Their exported native files
(`.kicad_pcb`, `.FCStd`, `.gltf`) sit alongside them.

| Example | Domain | Demonstrates |
| --- | --- | --- |
| [`hardware/blinky.forge.json`](hardware/blinky.forge.json) | hardware | Few-shot hardware reference: a resistor + LED imported from a real `.kicad_pcb`. |
| [`mechanical/box-with-hole.forge.json`](mechanical/box-with-hole.forge.json) | mechanical | Few-shot mechanical reference: a padded plate with a pocketed hole. |
| [`mechanical/motor-mount.forge.json`](mechanical/motor-mount.forge.json) | mechanical | An earlier motor-mount variant; pairs with `motor-mount.FCStd`. |
| [`threed/cube.forge.json`](threed/cube.forge.json) | threed | Few-shot threed reference: a single cube mesh with one material. |
