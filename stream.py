# SPDX-FileCopyrightText: 2026 Mikey Sklar
# SPDX-License-Identifier: MIT
"""Real-time streaming on the Fruit Jam: render the next chunk while the current one plays.

Nothing is prepared ahead of time. Every sample is generated on the board by the viper or C
kernel, a chunk at a time, and handed to an audiomixer voice the moment the previous chunk ends.
The five NeoPixels run as a level meter from the audio that is playing.
"""

import array
import math
import time

import audiocore
import audiomixer
import supervisor
from adafruit_fruitjam.peripherals import Peripherals

try:
    from resonator_c import resonate
    KIND = "C module"
except ImportError:
    from resonator import resonate
    KIND = "viper"

SR = 22050
BLOCK = 110  # samples per kernel call, 5 ms
CHUNK_BLOCKS = 400  # 2 s per chunk
CHUNKS = 10
WIN = 441  # 20 ms per LED update
FULL = 24000  # level that lights all five LEDs

fj = Peripherals(audio_output="headphone", sample_rate=SR)
fj.volume = 0.7
px = fj.neopixels
px.brightness = 0.25
px.auto_write = False

# Play through a Mixer, not straight to the DAC. RawSample on its own makes the RP2350 copy the
# whole clip into internal SRAM, which fails past about 1.9 s. A Mixer keeps that buffer at
# buffer_size no matter how long the clip is.
mixer = audiomixer.Mixer(voice_count=1, buffer_size=8192, sample_rate=SR, channel_count=1,
                         bits_per_sample=16, samples_signed=True)
mixer.voice[0].level = 0.5
fj.audio.play(mixer)

# Two buffers, allocated once. One plays while the other is rendered into. Allocating a fresh
# buffer per chunk stalls the interpreter for 200 to 300 ms, which is long enough to glitch.
N = BLOCK * CHUNK_BLOCKS
bufs = (array.array("h", bytes(2 * N)), array.array("h", bytes(2 * N)))
counts = (bytearray(N // WIN + 1), bytearray(N // WIN + 1))
st = array.array("i", [0x1234567, 0, 0, 0, 0, 0, 0])

COLORS = ((0, 255, 0), (120, 255, 0), (255, 200, 0), (255, 100, 0), (255, 0, 0))
playing = -1  # index of the buffer now playing, -1 before the first
t_play = 0
lit = -1


def led_tick():
    global lit
    n = 0
    if playing >= 0:
        k = ((supervisor.ticks_ms() - t_play) & 0x1FFFFFFF) // 20
        c = counts[playing]
        if k < len(c):
            n = c[k]
    if n != lit:
        for i in range(5):
            px[i] = COLORS[i] if i < n else (0, 0, 0)
        px.show()
        lit = n


def render(which, chunk):
    """Fill bufs[which]: noise through a resonator sweeping 300 to 3000 Hz, pulsing at 3 Hz."""
    buf = bufs[which]
    for i in range(CHUNK_BLOCKS):
        t = (chunk * CHUNK_BLOCKS + i) * BLOCK / SR
        freq = 1650 + 1350 * math.sin(2 * math.pi * 0.25 * t)
        env = 0.5 - 0.5 * math.cos(2 * math.pi * 3.0 * t)
        c = -math.exp(-2 * math.pi * 120 / SR)
        b = 2 * math.exp(-math.pi * 120 / SR) * math.cos(2 * math.pi * freq / SR)
        bq = round(b * 16384)
        cq = round(c * 16384)
        st[3] = int((16384 - bq - cq) * 2 * env)
        st[4] = bq
        st[5] = cq
        st[6] = i * BLOCK
        resonate(st, buf, BLOCK)
        if i & 3 == 0:
            led_tick()
    lv = counts[which]
    for w in range(len(lv)):
        s = buf[w * WIN:(w + 1) * WIN]
        p = max(max(s), -min(s)) if len(s) else 0
        lv[w] = min(5, p * 6 // FULL)


print("%s kernel, %d chunks of %.1f s" % (KIND, CHUNKS, N / SR))
for chunk in range(CHUNKS):
    which = chunk & 1
    t0 = time.monotonic_ns()
    render(which, chunk)
    ms = (time.monotonic_ns() - t0) / 1e6
    waited = 0
    while mixer.voice[0].playing:
        led_tick()
        time.sleep(0.004)
        waited += 4
    mixer.voice[0].play(audiocore.RawSample(bufs[which], sample_rate=SR))
    t_play = supervisor.ticks_ms()
    playing = which
    print("chunk %2d: %.1f s of audio rendered in %4.0f ms (%.2fx real time), idle %4d ms, peak %d"
          % (chunk, N / SR, ms, ms / (1000 * N / SR), waited, max(bufs[which])))
while mixer.voice[0].playing:
    led_tick()
    time.sleep(0.004)
playing = -1
led_tick()
