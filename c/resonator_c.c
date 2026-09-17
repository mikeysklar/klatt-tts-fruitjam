// SPDX-FileCopyrightText: 2026 Mikey Sklar
// SPDX-License-Identifier: MIT
// C module kernel: same arithmetic as resonator.py.

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
