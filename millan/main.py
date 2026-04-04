import can
import threading
import time
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

# ---------------------------------------------------------------------------
# Binary frame layout
#
# Each packed frame is 16 bytes:
#   [0:4]   ticks_ms  – u32 LE, milliseconds since session start (wraps ~49 days)
#   [4:8]   identity  – u32 LE, bit-packed:
#               bit 31      : bus ID      (0 = MCAN, 1 = VCAN)
#               bit 30      : is_extended (1 = 29-bit ID, 0 = 11-bit ID)
#               bits 28:0   : arbitration ID (masked to 29 or 11 bits)
#   [8:16]  payload   – u64 LE, up to 8 bytes of CAN data, zero-padded
# ---------------------------------------------------------------------------

MCAN_BUS_ID  = 0
VCAN_BUS_ID  = 1

BUS_ID_POS   = 31   # bit position for bus identifier
IS_EXTID_POS = 30   # bit position for extended-ID flag

# Shutdown coordination
shutdown_event = threading.Event()


# Bus helpers
def create_bus(device: str, baud_rate: int) -> can.interface.Bus | None:
    """Open a slcan CAN bus on the given serial device.

    Returns the Bus object on success, or None if the device is unavailable.
    The caller is responsible for calling bus.shutdown() when done.
    """
    try:
        bus = can.interface.Bus(interface='slcan', channel=device, bitrate=baud_rate)
        print(f"Connected to {device}")
        return bus
    except Exception as e:
        print(f"Failed to connect to {device}: {e}")
        return None


def pack_frame(msg: can.Message, ticks_ms: int, bus_id: int) -> bytes:
    """Encode a CAN message into the 16-byte binary frame format.

    The identity word carries bus, extended-ID flag, and arbitration ID
    all in a single u32, keeping the binary log compact and easy to parse
    with a single struct.unpack call on the reader side.
    """
    if bus_id == MCAN_BUS_ID:
        identity = MCAN_BUS_ID << BUS_ID_POS
    else:
        identity = VCAN_BUS_ID << BUS_ID_POS

    if msg.is_extended_id:
        # 29-bit extended ID: set flag + mask to 29 bits
        identity |= (1 << IS_EXTID_POS) | (msg.arbitration_id & 0x1FFF_FFFF)
    else:
        # 11-bit standard ID: mask to 11 bits
        identity |= msg.arbitration_id & 0x7FF

    # Zero-pad data to 8 bytes then unpack as a single u64 for the payload slot.
    # msg.data may be shorter than 8 bytes on data-length-code < 8 frames.
    payload, = struct.unpack_from('<Q', bytes(msg.data).ljust(8, b'\x00'))

    return struct.pack('<IIQ', ticks_ms, identity, payload)


# Reader thread
def read_bus(
    bus: can.interface.Bus,
    bus_id: int,
    queue: Queue,
    start_time_s: float,
    name: str,
) -> None:
    """Continuously read frames from one CAN bus and push them to the queue.

    Runs until shutdown_event is set.  Uses a short recv() timeout so the
    thread wakes regularly and can notice the shutdown flag.

    Remote frames and error frames are silently discarded; only data frames
    are logged (they are the only frames with meaningful payload bytes).
    """
    while not shutdown_event.is_set():
        try:
            message = bus.recv(timeout=0.1)
            if (
                message is not None
                and not message.is_remote_frame
                and not message.is_error_frame
            ):
                # Timestamp relative to session start, wrapped to u32
                ticks_ms = int((time.monotonic() - start_time_s) * 1000) & 0xFFFF_FFFF
                queue.put(pack_frame(message, ticks_ms, bus_id))
        except can.CanError as e:
            # Log and continue — a transient bus error should not kill the thread.
            # If the device is physically unplugged the errors will be frequent;
            # systemd will restart the whole process with Restart=always.
            print(f"[{name}] CAN error: {e}")

    print(f"[{name}] reader thread exit")


# Logger thread
def make_fname() -> str:
    """Return a timestamped log file path inside OUTDIR."""
    return f"{OUTDIR}/log-{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}.log"


def logger(queue: Queue) -> None:
    """Drain the frame queue to disk, rotating to a new file each interval.

    File management is done manually (not with a 'with' block) so that we
    can cleanly close and reopen mid-function without confusing the context
    manager.  The finally block guarantees the last file is always closed.

    On shutdown, any frames still in the queue are drained before the file
    is closed, so no data is lost during a clean exit.
    """
    fname = make_fname()
    last_rotate_s = time.monotonic()
    print(f"Logging to {fname}")

    f = open(fname, 'ab')
    try:
        while not shutdown_event.is_set():

            # --- File rotation ---
            if time.monotonic() - last_rotate_s >= NEW_FILE_INTERVAL_S:
                f.flush()
                os.fsync(f.fileno())    # ensure data survives a power cut
                f.close()
                fname = make_fname()
                print(f"Rotating log → {fname}")
                f = open(fname, 'ab')
                last_rotate_s = time.monotonic()

            # --- Frame write ---
            try:
                frame = queue.get(timeout=0.1)
                f.write(frame)
            except Empty:
                pass    # timeout is normal — loop back and check shutdown flag

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
        # Always close the file, even if an unexpected exception occurs
        f.close()

    print("Logger thread exit")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global shutdown_event

    start_time_s = time.monotonic()

    # Create log directory if it doesn't exist.
    # WorkingDirectory= in the systemd unit is set to /home/per/PER-RpiDaq/millan,
    # so './logs' resolves to /home/per/PER-RpiDaq/millan/logs.
    os.makedirs(OUTDIR, exist_ok=True)

    # Single queue shared by both reader threads → logger thread
    rx_can_queue: Queue = Queue()

    # Open both buses
    mcan_bus = create_bus(MCAN_DEVICE, BAUD_RATE)
    vcan_bus = create_bus(VCAN_DEVICE, BAUD_RATE)

    # Abort if either bus failed, systemd will restart after RestartSec=20
    if mcan_bus is None or vcan_bus is None:
        print("Could not open all CAN devices — exiting for systemd restart.")
        if mcan_bus:
            mcan_bus.shutdown()
        if vcan_bus:
            vcan_bus.shutdown()
        raise SystemExit(1)

    # Define threads
    mcan_thread    = threading.Thread(
        target=read_bus,
        args=(mcan_bus, MCAN_BUS_ID, rx_can_queue, start_time_s, "MCAN"),
        daemon=False,
    )
    vcan_thread    = threading.Thread(
        target=read_bus,
        args=(vcan_bus, VCAN_BUS_ID, rx_can_queue, start_time_s, "VCAN"),
        daemon=False,
    )
    logging_thread = threading.Thread(
        target=logger,
        args=(rx_can_queue,),
        daemon=False,
    )

    # Start threads
    mcan_thread.start()
    vcan_thread.start()
    logging_thread.start()

    # Main thread: just keeps the process alive and catches Ctrl-C / SIGTERM
    try:
        while not shutdown_event.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt — shutting down…")
        shutdown_event.set()

    # Signal any remaining threads that haven't noticed yet
    shutdown_event.set()

    # Join in dependency order: readers first (they feed the queue),
    # then the logger (so it can drain whatever the readers left behind)
    mcan_thread.join()
    vcan_thread.join()
    logging_thread.join()

    # Release the serial ports
    mcan_bus.shutdown()
    vcan_bus.shutdown()

    print("Clean exit")


if __name__ == "__main__":
    main()
