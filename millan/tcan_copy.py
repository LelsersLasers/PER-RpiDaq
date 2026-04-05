#!/usr/bin/env python3
"""mcan_daq.py — logs the Tranducer bus to logs/TCAN/"""

from daq_core import SingleBusLogger

DEVICE  = '/dev/ttyCANable2'
BUS_ID  = 0
OUTDIR  = './logs/TCAN'

if __name__ == "__main__":
    SingleBusLogger(device=DEVICE, bus_id=BUS_ID, outdir=OUTDIR, name="TCAN").run()