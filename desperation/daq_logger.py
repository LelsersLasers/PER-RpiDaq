#!/usr/bin/env python3
import can
import threading
import time
import struct
import os
from queue import Queue, Empty
from datetime import datetime

# 2 CAN devices --- MCAN & VCAN
vcan_device = '/dev/ttyCANable0'
mcan_device = '/dev/ttyCANable1'

# 500kbps bitrate
baud_rate = 500_000  

# log saving directory
OUTDIR = './logs'
NEW_FILE_INTERVAL_S = 60 * 1  # new file every minute 

# info for packing msg struct
MCAN_BUS_ID = 0
VCAN_BUS_ID = 1
 
BUS_ID_POS   = 31
IS_EXTID_POS = 30

last_log_time_s = time.monotonic()

# global user interrupt for individual threads to check 
userInterrupt = False;

def create_bus(device, baud_rate):
    try:
        bus = can.interface.Bus(interface='slcan', channel=device, bitrate=baud_rate)
        print(f"Connected to {device}")
        return bus
    except Exception as e:
        print(f"Failed to connect to {device}: {e}")
        return None

def read_bus(bus, bus_id, queue, start_time_s, name):
    global userInterrupt
    while not userInterrupt:
        try:
            message = bus.recv(timeout=0.1)
            if message is not None and not message.is_remote_frame and not message.is_error_frame:
                ticks_ms = int((time.monotonic() - start_time_s) * 1000) & 0xFFFFFFFF
                queue.put(pack_frame(message, ticks_ms, bus_id))
        except can.CanError as e:
            print(f"{name} error: {e}")
    print(f"{name} thread exit")

def pack_frame(msg, ticks_ms, bus):
    if (bus == MCAN_BUS_ID):
        identity = MCAN_BUS_ID << BUS_ID_POS
    else:
        identity = VCAN_BUS_ID << BUS_ID_POS
    if msg.is_extended_id:
        identity |= (1 << IS_EXTID_POS) | (msg.arbitration_id & 0x1FFF_FFFF)
    else:
        identity |= msg.arbitration_id & 0x7FF
    payload, = struct.unpack_from('<Q', bytes(msg.data).ljust(8, b'\x00'))
    return struct.pack('<IIQ', ticks_ms, identity, payload)

def make_fname():
    return f"{OUTDIR}/log-{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}.log"

def logger(queue):
    global userInterrupt
    fname = make_fname()
    last_log_time_s = time.monotonic()
    print(f"Logging to {fname}")
 
    with open(fname, 'ab') as f:
        while not userInterrupt:
            # Create new file if interval elapsed
            if time.monotonic() - last_log_time_s >= NEW_FILE_INTERVAL_S:
                f.flush()
                os.fsync(f.fileno())
                fname = make_fname()
                print(f"Creating new file: {fname}")
                f.close()
                f = open(fname, 'ab')
                last_log_time_s = time.monotonic()
 
            try:
                frame = queue.get(timeout=0.1)
                f.write(frame)
            except Empty:
                pass
 
        # Drain remaining frames on shutdown
        while not queue.empty():
            f.write(queue.get_nowait())
        f.flush()
        os.fsync(f.fileno())
 
    print("Logger thread exit")

def main():
    global userInterrupt
    start_time_s = time.monotonic()
    os.makedirs(OUTDIR, exist_ok=True)

    # queue creation
    rx_can_queue = Queue()

    # bus creation
    mcan_bus = create_bus(mcan_device, baud_rate)
    vcan_bus = create_bus(vcan_device, baud_rate)

    # ensure serial ports exist
    if mcan_bus is None or vcan_bus is None:
        print("Could not connect to all CAN devices, exiting.")
        if mcan_bus: mcan_bus.shutdown()
        if vcan_bus: vcan_bus.shutdown()
        exit(1)
    # define threads
    mcan_thread    = threading.Thread(target=read_bus, args=(mcan_bus, MCAN_BUS_ID, rx_can_queue, start_time_s, "MCAN"))
    vcan_thread    = threading.Thread(target=read_bus, args=(vcan_bus, VCAN_BUS_ID, rx_can_queue, start_time_s, "VCAN"))
    logging_thread = threading.Thread(target=logger, args=(rx_can_queue,))

    # start threads
    mcan_thread.start()
    vcan_thread.start()
    logging_thread.start()

    while not userInterrupt:
        try:
            time.sleep(0.1)
        except KeyboardInterrupt:
            userInterrupt = True

    # cleanly end everything
    mcan_thread.join()
    vcan_thread.join()
    logging_thread.join()
    mcan_bus.shutdown()
    vcan_bus.shutdown()
    print("Clean exit")

if __name__ == "__main__":
    main()
