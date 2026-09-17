# SPDX-FileCopyrightText: 2026 Mikey Sklar
# SPDX-License-Identifier: MIT
# Filtered-noise sweep on the Fruit Jam, rendered by the C module or viper.

import array
import math
import time

import audiocore
from adafruit_fruitjam.peripherals import Peripherals

try:
    from resonator_c import resonate
    KIND = "C module"
except ImportError:
    from resonator import resonate
    KIND = "viper"

SR = 22050
BLOCK = 110  # 5 ms


def coeffs(freq, bw):
    c = -math.exp(-2 * math.pi * bw / SR)
    b = 2 * math.exp(-math.pi * bw / SR) * math.cos(2 * math.pi * freq / SR)
    bq = round(b * 16384)
    cq = round(c * 16384)
    return 16384 - bq - cq, bq, cq


st = array.array("i", [0x1234567, 0, 0, 0, 0, 0, 0])
out = array.array("h", bytes(2 * SR))  # 1 s

t = time.monotonic_ns()
blocks = len(out) // BLOCK
for i in range(blocks):
    st[3], st[4], st[5] = coeffs(300 + 2700 * i // blocks, 40)
    st[6] = i * BLOCK
    resonate(st, out, BLOCK)
print("%s: 1 s of audio in %.1f ms" % (KIND, (time.monotonic_ns() - t) / 1e6))

fj = Peripherals(audio_output="headphone", sample_rate=SR)
fj.volume = 0.7
fj.audio.play(audiocore.RawSample(out, sample_rate=SR))
while fj.audio.playing:
    time.sleep(0.05)
