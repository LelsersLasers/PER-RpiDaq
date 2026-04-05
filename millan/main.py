import can
import threading
import time
import datetime
import struct
import os
from queue import Queue, Empty
from datetime import datetime

# Device configuration
# USB port symlinks defined in /etc/udev/rules.d/99-canable.rules
VCAN_DEVICE = '/dev/ttyCANable0'   # top-left grey USB port
MCAN_DEVICE = '/dev/ttyCANable1'   # bottom grey USB port

# CAN bus bitrate (both buses run at the same rate)
BAUD_RATE = 500_000

# Logging configuration
OUTDIR = './logs'
NEW_FILE_INTERVAL_S = 60 * 1    # rotate to a new file every 60 seconds

RECONNECT_INTERVAL_S = 1.0

# ---------------------------------------------------------------------------
# Binary frame layout
#
# Each packed frame is 16 bytes:
#   [0:4]   ticks_ms  - u32 LE, milliseconds since session start (wraps ~49 days)
#   [4:8]   identity  - u32 LE, bit-packed:
#             bit 31      : bus ID      (0 = MCAN, 1 = VCAN)
#             bit 30      : is_extended (1 = 29-bit ID, 0 = 11-bit ID)
#             bits 28:0   : arbitration ID (masked to 29 or 11 bits)
#   [8:16]  payload   - u64 LE, up to 8 bytes of CAN data, zero-padded
# ---------------------------------------------------------------------------

MCAN_BUS_ID  = 0
VCAN_BUS_ID  = 1

BUS_ID_POS   = 31   # bit position for bus identifier
IS_EXTID_POS = 30   # bit position for extended-ID flag

# Shutdown coordination
shutdown_event = threading.Event()


# Bus helpers
def try_open_bus(device, baud_rate):
    """Attempt to open a slcan CAN bus. Returns None on failure."""
    try:
        bus = can.interface.Bus(interface='slcan', channel=device, bitrate=baud_rate)
        print(f"[{device}] Connected")
        return bus
    except Exception as e:
        print("f[{device}] failed to connect")
        return None


def pack_frame(msg, ticks_ms, bus_id):
    """Encode a CAN message into the 16-byte binary frame format."""
    if bus_id == MCAN_BUS_ID:
        identity = MCAN_BUS_ID << BUS_ID_POS
    else:
        identity = VCAN_BUS_ID << BUS_ID_POS

    if msg.is_extended_id:
        identity |= (1 << IS_EXTID_POS) | (msg.arbitration_id & 0x1FFF_FFFF)
    else:
        identity |= msg.arbitration_id & 0x7FF

    payload, = struct.unpack_from('<Q', bytes(msg.data).ljust(8, b'\x00'))
    return struct.pack('<IIQ', ticks_ms, identity, payload)


# ---------------------------------------------------------------------------
# Reader thread
#
# Each reader thread owns its bus connection entirely - it opens it, reads
# from it, and re-opens it if it disappears. The main thread no longer
# manages bus lifetime at all.
#
# State machine per thread:
#   DISCONNECTED -> try_open_bus() every RECONNECT_INTERVAL_S
#   CONNECTED    -> recv() loop; on any error -> shutdown bus -> DISCONNECTED
# ---------------------------------------------------------------------------

def read_bus(device, bus_id, queue, start_time_s, name):
    """Resilient reader: reconnects automatically if the device is absent or
    disconnects mid-run. Runs until shutdown_event is set."""

    bus = None

    while not shutdown_event.is_set():

        # --- DISCONNECTED: try to open the device ---
        if bus is None:
            bus = try_open_bus(device, BAUD_RATE)
            if bus is None:
                # Device not available yet - wait and retry
                print(f"[{name}] Waiting for {device} ...")
                # Sleep in small increments so we notice shutdown quickly
                for _ in range(int(RECONNECT_INTERVAL_S / 0.5)):
                    if shutdown_event.is_set():
                        break
                    time.sleep(0.5)
                continue   # back to top of loop to retry open

        # --- CONNECTED: read frames ---
        try:
            message = bus.recv(timeout=0.1)
            if (
                message is not None
                and not message.is_remote_frame
                and not message.is_error_frame
            ):
                ticks_ms = int((time.monotonic() - start_time_s) * 1000) & 0xFFFF_FFFF
                queue.put(pack_frame(message, ticks_ms, bus_id))

        except can.CanError as e:
            # Any CAN error (including device unplug) triggers a reconnect cycle
            print(f"[{name}] CAN error: {e} - attempting reconnect")
            try:
                bus.shutdown()
            except Exception:
                pass   # best-effort; the device may already be gone
            bus = None   # fall back to DISCONNECTED state on next iteration

        except Exception as e:
            # Catch-all for unexpected errors (e.g. serial port disappearing)
            print(f"[{name}] Unexpected error: {e} - attempting reconnect")
            try:
                bus.shutdown()
            except Exception:
                pass
            bus = None

    # --- Shutdown: cleanly close the bus if it's open ---
    if bus is not None:
        try:
            bus.shutdown()
        except Exception:
            pass

    print(f"[{name}] reader thread exit")


# ---------------------------------------------------------------------------
# Logger thread
# ---------------------------------------------------------------------------

def make_fname():
    """Return a timestamped log file path inside OUTDIR."""
    return f"{OUTDIR}/log-{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}.log"


def logger(queue):
    """Drain the frame queue to disk, rotating to a new file each interval."""
    fname = make_fname()
    last_rotate_s = time.monotonic()
    print(f"Logging to {fname}")

    f = open(fname, 'ab')
    try:
        while not shutdown_event.is_set():

            # --- File rotation ---
            if time.monotonic() - last_rotate_s >= NEW_FILE_INTERVAL_S:
                f.flush()
                os.fsync(f.fileno())
                f.close()
                fname = make_fname()
                print(f"Rotating log -> {fname}")
                f = open(fname, 'ab')
                last_rotate_s = time.monotonic()

            # --- Frame write ---
            try:
                frame = queue.get(timeout=0.1)
                f.write(frame)
            except Empty:
                pass

        # --- Drain remaining frames on clean shutdown ---
        drained = 0
        while not queue.empty():
            f.write(queue.get_nowait())
            drained += 1

        f.flush()
        os.fsync(f.fileno())
        if drained:
            print(f"Drained {drained} buffered frame(s) on shutdown")

    finally:
        f.close()

    print("Logger thread exit")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"\n\nSTARTING: {datetime.now()}")
    
    start_time_s = time.monotonic()
    os.makedirs(OUTDIR, exist_ok=True)

    rx_can_queue = Queue()

    # Each reader thread manages its own bus connection - no bus objects here
    mcan_thread = threading.Thread(
        target=read_bus,
        args=(MCAN_DEVICE, MCAN_BUS_ID, rx_can_queue, start_time_s, "MCAN"),
        daemon=False,
    )
    vcan_thread = threading.Thread(
        target=read_bus,
        args=(VCAN_DEVICE, VCAN_BUS_ID, rx_can_queue, start_time_s, "VCAN"),
        daemon=False,
    )
    logging_thread = threading.Thread(
        target=logger,
        args=(rx_can_queue,),
        daemon=False,
    )

    mcan_thread.start()
    vcan_thread.start()
    logging_thread.start()

    try:
        while not shutdown_event.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt - shutting down...")
        shutdown_event.set()

    shutdown_event.set()

    mcan_thread.join()
    vcan_thread.join()
    logging_thread.join()

    print("Clean exit")


if __name__ == "__main__":
    main()
