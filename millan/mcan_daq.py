#!/usr/bin/env python3
"""mcan_daq.py — logs the MCAN bus to logs/MCAN/"""

from daq_core import SingleBusLogger

DEVICE  = '/dev/ttyCANable1'
BUS_ID  = 0
OUTDIR  = './logs/MCAN'

if __name__ == "__main__":
    SingleBusLogger(device=DEVICE, bus_id=BUS_ID, outdir=OUTDIR, name="MCAN").run()