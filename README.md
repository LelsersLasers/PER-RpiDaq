# PER-RpiDaq

Bootstrapping a Raspberry Pi 5 to function as DAQ for early car testing/before DAQ26 is here.

- Username: `per`
- Password: `per`
- IP in AP mode: `10.42.0.1`
- SSH: `ssh per@10.42.0.1`
- Wifi passoword: `12345678`
- Wifi SSID: `PER-DaqRpi Wifi`

## Where things go

- `millan/99-canable.rules` -> `/etc/udev/rules.d/99-canable.rules`
  - `sudo udevadm control --reload-rules && sudo udevadm trigger`
- `millan/vcan.service` -> `/etc/systemd/system/vcan.service`
  - `sudo systemctl daemon-reload && sudo systemctl enable vcan.service && sudo systemctl start vcan.service`
- `millan/mcan.service` -> `/etc/systemd/system/mcan.service`
  - `sudo systemctl daemon-reload && sudo systemctl enable mcan.service && sudo systemctl start mcan.service`

## Access point mode

```bash
sudo nmcli device wifi hotspot \
  ifname wlan0 \
  ssid "PER-RpiDaq Wifi" \
  password "12345678" \
  con-name "hotspot"
```
```bash
sudo nmcli connection modify hotspot \
  connection.autoconnect yes \
  connection.autoconnect-priority 999
```

## Canables

- Grey top = `ttyCANable0` = VCAN
- Grey bottom = `ttyCANable1` = MCAN
- Blue top = `ttyCANable2` = Tranducer
