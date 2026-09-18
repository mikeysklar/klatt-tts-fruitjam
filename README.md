# klatt-tts-fruitjam

### [▶ Watch it talk: the Fruit Jam reads Alice in Wonderland (video)](https://drive.google.com/file/d/1pOplKIgTwtMqX1uFa3xJQ6wXBjnOFmpp/view?usp=sharing)

Everything you hear in the video is made on the board itself, an Adafruit Fruit Jam running stock
CircuitPython. It starts from plain text. There are no audio files and no computer helping. The
hot loop is viper code, and the board made those 45 seconds of speech in 35 seconds.

This repo shows how we got CircuitPython fast enough to do that, with a small example you can run.

## How fast is it?

A speech synthesizer saying "circuit python" (1.86 s of audio, 41,030 samples at 22,050 Hz):

| Version | Time | µs/sample | vs Python | vs viper | `.mpy` |
|---|---|---|---|---|---|
| Python (floats) | 43.3 s | 1,055 | 1x | | source only |
| Viper, fixed point | 216.8 ms | 5.28 | 200x | 1x | 3,263 B |
| C module `-Os` | 95.8 ms | 2.33 | 453x | 2.3x | 1,573 B |
| **C module `-O2`** | **87.9 ms** | **2.14** | **493x** | **2.5x** | **1,644 B** |

The Python row is the whole synth. The others time only the per-sample loop. Here is the whole
job, start to finish:

| Version | Render time | Real-time factor |
|---|---|---|
| Python (floats) | 43.3 s | 23.3 |
| Viper | 0.744 s | 0.40 |
| C module `-O2` | 0.613 s | 0.33 |

A real-time factor under 1 means the audio is ready before it is needed.

What this means for you:

- **Plain CircuitPython is far too slow for audio.** 43 seconds to make 2 seconds of sound.
- **Viper gets you almost all of the speedup.** 200x faster, and it is still just Python. Add one
  decorator, keep the math to integers, compile with `mpy-cross`.
- **C helps less than you would think.** The loop itself gets 2.5x faster, but by then the loop is a
  small slice of the total, so the whole job only gets about 20% faster. Reading a book aloud, viper
  ran at 0.69x real time and C at 0.60x. Start with viper. Only reach for C if you still need more.

## What is in this repo

| File | What it does |
|---|---|
| `resonator.py` | A small audio loop in viper: noise through a filter |
| `stream.py` | Plays it in real time, with the five NeoPixels as a level meter |
| `code.py` | The shortest possible version: render one second, play it |
| `c/` | The same loop as a C module, if you want to try that too |

The speech synthesizer from the video is not in here yet. It is a port of
[Moonshine's](https://github.com/moonshine-ai/moonshine) `micro/klatt-tts`, and we are waiting for
them to confirm the license ([issue #228](https://github.com/moonshine-ai/moonshine/issues/228)).
The example here is built exactly the same way, so everything you learn carries over.

## What you need

- A Fruit Jam running CircuitPython 10.3.1 or newer.
- A CircuitPython checkout that matches your firmware, to build `mpy-cross`.

```sh
git clone https://github.com/adafruit/circuitpython
cd circuitpython
git checkout 10.3.1
make -C mpy-cross                 # builds mpy-cross/build/mpy-cross
```

## The viper loop

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

Build it and copy it over:

```sh
/path/to/circuitpython/mpy-cross/build/mpy-cross -march=armv7emsp resonator.py
cp resonator.mpy stream.py /Volumes/CIRCUITPY/
```

Things that tripped us up:

- Viper only speeds up integer math. Use fixed point: samples Q12, filter coefficients Q14.
- `>>` keeps the sign on `int` and does not on `uint`. That is why the noise generator has `uint` casts.
- Integers wrap around at 32 bits.
- Calling one viper function from another is slow. Keep the whole loop in one function.
- You cannot compile viper on the board. `@micropython.viper` at the REPL gives
  `SyntaxError: invalid micropython decorator`. Use `mpy-cross`.

## Play it in real time

`stream.py` makes sound the way the speech synth does. Nothing is prepared ahead of time. It renders
the next 2 seconds while the current 2 seconds play, and the NeoPixels follow the audio.

All playback goes through an `audiomixer.Mixer`. This is the part that made long audio work:

```python
mixer = audiomixer.Mixer(voice_count=1, buffer_size=8192, sample_rate=22050, channel_count=1,
                         bits_per_sample=16, samples_signed=True)
mixer.voice[0].level = 0.5
fj.audio.play(mixer)                       # the mixer plays forever

mixer.voice[0].play(audiocore.RawSample(buf, sample_rate=22050))   # hand it each chunk
while mixer.voice[0].playing:
    time.sleep(0.004)
```

For speech we run `level = 1.0` and `fj.volume = 0.75`. The noise example is louder, so it uses 0.5.

On the REPL, `import stream`, or rename it to `code.py`. Output from our board:

```
viper kernel, 10 chunks of 2.0 s
chunk  1: 2.0 s of audio rendered in  238 ms (0.12x real time), idle 1608 ms
chunk  2: 2.0 s of audio rendered in  229 ms (0.12x real time), idle 1704 ms
```

Each chunk takes about a quarter of a second to make, then the board waits for the speaker to
catch up. With the C module it is 0.10x. Either way there is lots of room to do more.

Fruit Jam tips:

- **Play through a Mixer.** `RawSample` on its own copies the whole clip into a small pool of fast
  memory, and anything past about 1.9 s fails with `Unable to allocate buffers for signed
  conversion`. Through `audiomixer.Mixer` we played 13 s clips with no trouble. If you do hit that
  error, a soft reset does not clear it. Use `microcontroller.reset()`.
- **Make your buffers once.** Allocating a big buffer takes 200 to 300 ms, long enough to make the
  audio skip. `stream.py` makes two up front and takes turns.
- **Volume.** `fj.volume` moves the DAC about 11 dB per 0.1. At 0.35 we heard nothing. 0.7 is good,
  and 0.75 is the most the library allows.
- Use `audio_output="speaker"` for the small speaker connector instead of the headphone jack.

## Optional: the same loop in C

Viper is the easy win, so try that first. If you want the last bit of speed, the same loop can be a
C module. It is still a `.mpy` file you copy to the board. No custom firmware.

You also need `arm-none-eabi-gcc` (tested with 14.3.1 and 15.2.1) and two Python packages:

```sh
cd circuitpython
python -m venv venv
venv/bin/pip install pyelftools ar # needed by tools/mpy_ld.py
```

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

Build and copy:

```sh
cd c
make MPY_DIR=/path/to/circuitpython PYTHON=/path/to/circuitpython/venv/bin/python
cp resonator_c.mpy /Volumes/CIRCUITPY/
```

`stream.py` and `code.py` use the C module if it is on the board and fall back to viper if not.

- The build defaults to `-Os`. Adding `-O2` after the include overrides it.
- `-fwrapv` makes integer overflow wrap, the same as viper, so both versions give identical audio.
- C writes straight into your buffers, so check the lengths first.
- `armv7emsp` covers RP2350, SAMD51 and nRF52840. The wrong one fails at import with
  `ValueError: incompatible .mpy arch`.

For this small example, one call of 22,050 samples:

| Version | Time | µs/sample | vs viper | `.mpy` |
|---|---|---|---|---|
| Viper | 26.3 ms | 1.192 | 1x | 487 B |
| C module `-O2` | 8.1 ms | 0.368 | 3.2x | 434 B |

All numbers are from a Fruit Jam (RP2350B at 150 MHz), medians of 5 to 7 runs with under 1 ms
spread. Viper and C produced identical samples every time.

## License

MIT. See `LICENSE`.
