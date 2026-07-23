"""Generate the placeholder wood-plank texture shipped with textured_crate.

Deterministic (fixed seed, no randomness at all) so the committed PNG is
reproducible from this description: four horizontal planks with darker gaps
and a few grain streaks per plank.
"""

import math
import pathlib

from PIL import Image

SIZE = 128
PLANKS = 4
img = Image.new("RGB", (SIZE, SIZE))
px = img.load()
plank_h = SIZE // PLANKS
for y in range(SIZE):
    row = y // plank_h
    edge = y % plank_h
    for x in range(SIZE):
        # Base wood tone, shifted a little per plank so the rows read apart.
        base = (150 + 12 * ((row * 5) % 3), 100 + 9 * (row % 3), 55 + 7 * ((row * 2) % 3))
        # Grain: a low-frequency sine along x, phase-offset per plank.
        grain = math.sin((x / SIZE) * math.pi * 6 + row * 1.7) * 10
        grain += math.sin((x / SIZE) * math.pi * 23 + row) * 5
        # Dark seam between planks, and a subtle plank-end notch.
        seam = edge < 2 or edge >= plank_h - 2
        shade = -55 if seam else grain
        px[x, y] = tuple(max(0, min(255, int(c + shade))) for c in base)
img.save(pathlib.Path("examples/threed/textures/wood_planks.png"), optimize=True)
print("wrote", SIZE, "x", SIZE, "PNG")
