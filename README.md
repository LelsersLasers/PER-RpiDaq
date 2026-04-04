# PER-RpiDaq

Bootstrapping a Raspberry Pi 5 to function as DAQ for early car testing/before DAQ26 is here.

- Host name: `rpi-daq.local`
- Username: `per`
- Password: `per`
- IP in AP mode: `10.42.0.1`
- SSH: `ssh per@10.42.0.1`

## Where things go

- `millan/99-canable.rules` -> `/etc/udev/rules.d/99-canable.rules`
  - `sudo udevadm control --reload-rules && sudo udevadm trigger`
- `millan/rpi-daq.service` -> `/etc/systemd/system/rpi-daq.service`
  - `sudo systemctl daemon-reload && sudo systemctl enable millan.service && sudo systemctl start millan.service`

## Access point mode

```bash
sudo nmcli device wifi hotspot \
  ifname wlan0 \
  ssid "PER-RpiDaq" \
  password "per" \
  con-name "hotspot"
```
```bash
sudo nmcli connection modify hotspot \
  connection.autoconnect yes \
  connection.autoconnect-priority 10
```
