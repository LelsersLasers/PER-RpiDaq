#!/usr/bin/env python3
import can

# Configuration for the SLCAN device
slcan_device = '/dev/ttyCANable0'
baud_rate = 500000  # Set the appropriate baud rate for your setup

# Create a CAN bus instance using the SLCAN interface
bus = can.interface.Bus(interface='slcan', channel=slcan_device, bitrate=baud_rate)

try:
    print("Listening for CAN messages on", slcan_device)
    while True:
        # Read a message from the CAN bus
        message = bus.recv()

        if message is not None:
            print(f"Received: {message}")

except KeyboardInterrupt:
    print("Stopped by user")

except can.CanError as e:
    print(f"CAN error: {e}")
finally:
    bus.shutdown()
    print("Bus shut down cleanly.")
