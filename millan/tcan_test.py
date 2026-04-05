import can

bus = can.interface.Bus(
    interface="slcan",
    channel="/dev/ttyACM0",
    bitrate=1000000
)

print("Listening...")
while True:
    msg = bus.recv(timeout=1.0)
    if msg is not None:
        print(msg)
    else:
        print("No message received within timeout")
