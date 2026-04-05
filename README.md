# PER-RpiDaq

Bootstrapping a Raspberry Pi 5 to function as DAQ for early car testing/before DAQ26 is here.

- Username: `per`
- Password: `per`
- IP in AP mode: `10.42.0.1`
- SSH: `ssh per@10.42.0.1`
- Wifi passoword: `12345678`
- Wifi SSID: `PER-DaqRpi Wifi`

## How to use

### Default

The Pi should turn on and init all 3 canables and start logging without any intervention

### Get logs

1. On laptop: connect to `PER-DaqRpi Wifi` (password: `12345678`)
2. On laptop: move to the `millan` folder (`cd millan`)
3. On laptop: copy logs: `bash scp_logs.sh`
4. On laptop: rename `millan/copied/logs` to something like `millan/copied/logs_some_text_that_is_useful`
4. Remove old logs: `bash ssh.sh` and then (now on RPI) `cd PER-RpiDaq/millan/logs` and then `rm -vr *`
  - Don't remove the `logs` folder itself other wise the loggers will crash
  - This is done because the RPI keeps bad real time
5. :money: :vd_happy:

## Where things go

(once)

- canable udev rules:
  - `millan/99-canable.rules` -> `/etc/udev/rules.d/99-canable.rules`
  - `sudo udevadm control --reload-rules && sudo udevadm trigger`
- systemd services:
  - `millan/vcan.service` -> `/etc/systemd/system/vcan.service`
  - `millan/mcan.service` -> `/etc/systemd/system/mcan.service`
  - `millan/tcan.service` -> `/etc/systemd/system/tcan.service`
  - ```bash
    sudo systemctl daemon-reload && \
      sudo systemctl enable vcan.service && sudo systemctl start vcan.service && \
      sudo systemctl enable mcan.service && sudo systemctl start mcan.service && \
      sudo systemctl enable tcan.service && sudo systemctl start tcan.service
    ```

## Access point mode

(once)

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
