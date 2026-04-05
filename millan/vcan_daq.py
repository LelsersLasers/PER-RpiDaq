#!/usr/bin/env python3
"""vcan_daq.py — logs the VCAN bus to logs/VCAN/"""

from daq_core import SingleBusLogger

DEVICE  = '/dev/ttyCANable0'
BUS_ID  = 1
OUTDIR  = './logs/VCAN'

if __name__ == "__main__":
    SingleBusLogger(device=DEVICE, bus_id=BUS_ID, outdir=OUTDIR, name="VCAN").run()