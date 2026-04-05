#!/usr/bin/env python3
"""
daq_core.py — shared CAN logging logic.
Instantiate and run a SingleBusLogger for a given device/bus.
"""

import can
import threading
import time
import struct
import os
from queue import Queue, Empty
from datetime import datetime

# 500 kbps bitrate (shared default, overridable)
DEFAULT_BAUD_RATE = 500_000

# Rotate to a new file every minute
NEW_FILE_INTERVAL_S = 60 * 1

# Bit-field positions inside the packed identity word
BUS_ID_POS   = 31
IS_EXTID_POS = 30


# ── helpers ──────────────────────────────────────────────────────────────────

def create_bus(device: str, baud_rate: int) -> can.BusABC | None:
    try:
        bus = can.interface.Bus(interface='slcan', channel=device, bitrate=baud_rate)
        print(f"Connected to {device}")
        return bus
    except Exception as e:
        print(f"Failed to connect to {device}: {e}")
        return None


def pack_frame(msg: can.Message, ticks_ms: int, bus_id: int) -> bytes:
    identity = bus_id << BUS_ID_POS
    if msg.is_extended_id:
        identity |= (1 << IS_EXTID_POS) | (msg.arbitration_id & 0x1FFF_FFFF)
    else:
        identity |= msg.arbitration_id & 0x7FF
    payload, = struct.unpack_from('<Q', bytes(msg.data).ljust(8, b'\x00'))
    return struct.pack('<IIQ', ticks_ms, identity, payload)


def make_fname(outdir: str) -> str:
    return f"{outdir}/log-{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}.log"


# ── thread workers ────────────────────────────────────────────────────────────

def _read_bus(bus: can.BusABC, bus_id: int, queue: Queue,
              start_time_s: float, name: str, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            message = bus.recv(timeout=0.1)
            if message is not None \
                    and not message.is_remote_frame \
                    and not message.is_error_frame:
                ticks_ms = int((time.monotonic() - start_time_s) * 1000) & 0xFFFF_FFFF
                queue.put(pack_frame(message, ticks_ms, bus_id))
        except can.CanError as e:
            print(f"{name} error: {e}")
        except ValueError:
            # python-can slcan driver bug: DLC field can be a hex letter
            # (e.g. 'F') on some extended frames, causing int() to fail.
            # The frame is unrecoverable => skip it
            print(f"{name} warning: skipping malformed frame")
            pass
    print(f"{name} reader thread exit")


def _logger(queue: Queue, outdir: str, stop_event: threading.Event):
    fname = make_fname(outdir)
    last_rotate_s = time.monotonic()
    print(f"Logging to {fname}")

    with open(fname, 'ab') as f:
        while not stop_event.is_set():
            if time.monotonic() - last_rotate_s >= NEW_FILE_INTERVAL_S:
                f.flush()
                os.fsync(f.fileno())
                fname = make_fname(outdir)
                print(f"Creating new file: {fname}")
                f.close()
                f = open(fname, 'ab')
                last_rotate_s = time.monotonic()

            try:
                frame = queue.get(timeout=0.1)
                f.write(frame)
            except Empty:
                pass

        # drain remaining frames on shutdown
        while not queue.empty():
            f.write(queue.get_nowait())
        f.flush()
        os.fsync(f.fileno())

    print("Logger thread exit")


# ── public API ────────────────────────────────────────────────────────────────

class SingleBusLogger:
    """Log one CAN bus to its own output directory."""

    def __init__(self, device: str, bus_id: int, outdir: str,
                 baud_rate: int = DEFAULT_BAUD_RATE, name: str = "CAN"):
        self.device    = device
        self.bus_id    = bus_id
        self.outdir    = outdir
        self.baud_rate = baud_rate
        self.name      = name

    def run(self):
        os.makedirs(self.outdir, exist_ok=True)
        start_time_s = time.monotonic()
        stop_event   = threading.Event()
        queue        = Queue()

        bus = create_bus(self.device, self.baud_rate)
        if bus is None:
            print(f"Could not connect to {self.device}, exiting.")
            return

        reader_thread = threading.Thread(
            target=_read_bus,
            args=(bus, self.bus_id, queue, start_time_s, self.name, stop_event),
            daemon=True,
        )
        logger_thread = threading.Thread(
            target=_logger,
            args=(queue, self.outdir, stop_event),
            daemon=True,
        )

        reader_thread.start()
        logger_thread.start()

        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print(f"\n{self.name}: interrupt received, shutting down…")
        finally:
            stop_event.set()
            reader_thread.join()
            logger_thread.join()
            bus.shutdown()
            print(f"{self.name}: clean exit")