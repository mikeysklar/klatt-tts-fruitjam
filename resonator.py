# SPDX-FileCopyrightText: 2026 Mikey Sklar
# SPDX-License-Identifier: MIT
# Viper kernel: xorshift noise through a Q14 two-pole resonator.
# Build: mpy-cross -march=armv7emsp resonator.py

import micropython

# st (array 'i'): rng, y1, y2, a, b, c, offset


@micropython.viper
def resonate(st: ptr32, out: ptr16, n: int) -> int:
    r = int(st[0])
    y1 = int(st[1])
    y2 = int(st[2])
    a = int(st[3])
    b = int(st[4])
    c = int(st[5])
    off = int(st[6])
    s = 0
    while s < n:
        r = r ^ (r << 13)
        r = r ^ int(uint(r) >> 17)
        r = r ^ (r << 5)
        x = int(uint(r) >> 20) - 2048
        y = (a * x + b * y1 + c * y2 + 8192) >> 14
        y2 = y1
        y1 = y
        if y > 32767:
            y = 32767
        if y < -32768:
            y = -32768
        out[off + s] = y
        s += 1
    st[0] = r
    st[1] = y1
    st[2] = y2
    return n
