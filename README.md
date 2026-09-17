# klatt-tts-fruitjam

Speeding up a CircuitPython audio loop on the Adafruit Fruit Jam (RP2350B, 150 MHz Cortex-M33),
first with viper, then with a C native module. Both are `.mpy` files built on a host and copied to
CIRCUITPY. No custom firmware.

The example here is a filtered-noise kernel. The performance table at the bottom is from a Klatt
formant speech synthesizer built the same way.

## Requirements

- Fruit Jam running CircuitPython 10.3.1 or newer (native module loading is built in).
- A CircuitPython checkout whose `.mpy` version matches the firmware (6.3 for 10.3.x and 10.4.x).
- `arm-none-eabi-gcc` (tested with 14.3.1 and 15.2.1).

## Setup

```sh
git clone https://github.com/adafruit/circuitpython
cd circuitpython
git checkout 10.3.1
make -C mpy-cross                 # builds mpy-cross/build/mpy-cross
python -m venv venv
venv/bin/pip install pyelftools ar # needed by tools/mpy_ld.py
```

## Viper

`resonator.py`:

```python
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
```

Build:

```sh
/path/to/circuitpython/mpy-cross/build/mpy-cross -march=armv7emsp resonator.py
```

Notes:

- Viper only speeds up integer code, so the loop is integer only: samples Q12, coefficients Q14.
- `>>` is arithmetic on `int` and logical on `uint`, hence the `uint` casts in the xorshift.
- Integers wrap at 32 bits.
- Calls between viper functions go through the runtime, so keep the whole loop in one function.
- The on-board compiler is off. `@micropython.viper` at the REPL gives
  `SyntaxError: invalid micropython decorator`. Compile with `mpy-cross`.

## C native module

`c/resonator_c.c`:

```c
#include "py/dynruntime.h"

// st (array 'i'): rng, y1, y2, a, b, c, offset
static void c_resonate(int32_t *st, int16_t *out, int32_t n) {
    uint32_t r = (uint32_t)st[0];
    int32_t y1 = st[1], y2 = st[2];
    const int32_t a = st[3], b = st[4], c = st[5], off = st[6];
    for (int32_t s = 0; s < n; s++) {
        r ^= r << 13;
        r ^= r >> 17;
        r ^= r << 5;
        int32_t x = (int32_t)(r >> 20) - 2048;
        int32_t y = (a * x + b * y1 + c * y2 + 8192) >> 14;
        y2 = y1;
        y1 = y;
        if (y > 32767) {
            y = 32767;
        }
        if (y < -32768) {
            y = -32768;
        }
        out[off + s] = (int16_t)y;
    }
    st[0] = (int32_t)r;
    st[1] = y1;
    st[2] = y2;
}

static mp_obj_t resonate(mp_obj_t st_in, mp_obj_t out_in, mp_obj_t n_in) {
    mp_buffer_info_t st, out;
    mp_get_buffer_raise(st_in, &st, MP_BUFFER_RW);
    mp_get_buffer_raise(out_in, &out, MP_BUFFER_WRITE);
    mp_int_t n = mp_obj_get_int(n_in);
    if (st.len < 7 * 4) {
        mp_raise_ValueError(MP_ERROR_TEXT("st too small"));
    }
    int32_t *s = st.buf;
    if (n < 0 || s[6] < 0 || (size_t)(s[6] + n) * 2 > out.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("out too small"));
    }
    c_resonate(s, out.buf, n);
    return MP_OBJ_NEW_SMALL_INT(n);
}
static MP_DEFINE_CONST_FUN_OBJ_3(resonate_obj, resonate);

mp_obj_t mpy_init(mp_obj_fun_bc_t *self, size_t n_args, size_t n_kw, mp_obj_t *args) {
    MP_DYNRUNTIME_INIT_ENTRY
    mp_store_global(MP_QSTR_resonate, MP_OBJ_FROM_PTR(&resonate_obj));
    MP_DYNRUNTIME_INIT_EXIT
}
```

`c/Makefile`:

```make
MPY_DIR ?= ../../circuitpython
ARCH ?= armv7emsp
MOD = resonator_c
SRC = resonator_c.c
include $(MPY_DIR)/py/dynruntime.mk
# Appended after the include, so -O2 overrides the -Os default.
CFLAGS += -fwrapv -O2
```

Build:

```sh
cd c
make MPY_DIR=/path/to/circuitpython PYTHON=/path/to/circuitpython/venv/bin/python
```

Notes:

- `dynruntime.mk` builds at `-Os`. The last `-O` on the command line wins, so appending `-O2`
  after the include overrides it.
- `-fwrapv` makes signed overflow wrap, matching viper.
- C writes into the buffers directly, so check the lengths before the loop.
- `armv7emsp` is the arch for RP2350, SAMD51 and nRF52840. The wrong one fails at import with
  `ValueError: incompatible .mpy arch`.

## On the board

```
CIRCUITPY/
├── code.py
├── resonator_c.mpy      ← C loop, ARM machine code
└── resonator.mpy        ← viper loop
```

```sh
cp resonator.mpy c/resonator_c.mpy code.py /Volumes/CIRCUITPY/
```

`code.py`:

```python
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
```

Fruit Jam notes:

- `volume` maps to the DAC at about 11 dB per 0.1: 0.35 is -32.5 dB (inaudible), 0.7 is -2.5 dB.
  The cap is 0.75.
- Use `audio_output="speaker"` for the JST-SH speaker connector.
- `RawSample` copies the whole sample into internal SRAM. About 1 s (44 KB) is fine, 3 s (132 KB)
  raises `RuntimeError: Unable to allocate buffers for signed conversion`. Play long audio in chunks.

## Performance

Fruit Jam, RP2350B at 150 MHz. Medians of 5 to 7 runs, with under 1 ms spread. Viper and C
produced identical samples in every case.

Example kernel above, one call of 22,050 samples:

| Version | Time | µs/sample | vs viper | `.mpy` |
|---|---|---|---|---|
| Viper | 26.3 ms | 1.192 | 1x | 487 B |
| C module `-O2` | 8.1 ms | 0.368 | 3.2x | 434 B |

Klatt formant speech synthesizer, built the same way, saying "circuit python" (41,030 samples,
1.86 s of audio at 22,050 Hz):

| Version | Time | µs/sample | vs Python | vs viper | `.mpy` |
|---|---|---|---|---|---|
| Python (floats) | 43.3 s | 1,055 | 1x | | source only |
| Viper, fixed point | 216.8 ms | 5.28 | 200x | 1x | 3,263 B |
| C module `-Os` | 95.8 ms | 2.33 | 453x | 2.3x | 1,573 B |
| **C module `-O2`** | **87.9 ms** | **2.14** | **493x** | **2.5x** | **1,644 B** |

The Python row is the whole synth; the others time only the per-sample loop. Whole renders,
including the Python-side setup that runs once per 5 ms frame:

| Version | Render time | Real-time factor |
|---|---|---|
| Python (floats) | 43.3 s | 23.3 |
| Viper | 0.744 s | 0.40 |
| C module `-O2` | 0.613 s | 0.33 |

The speech synthesizer itself is not in this repo. It is a port of third-party code whose license
terms are still being confirmed.

## License

MIT. See `LICENSE`.
