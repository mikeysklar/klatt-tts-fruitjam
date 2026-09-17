MPY_DIR ?= ../../circuitpython
ARCH ?= armv7emsp
MOD = resonator_c
SRC = resonator_c.c
include $(MPY_DIR)/py/dynruntime.mk
# Appended after the include, so -O2 overrides the -Os default.
CFLAGS += -fwrapv -O2
