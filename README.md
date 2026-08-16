# Network Traffic Monitoring with Analog Gauges

This project monitors network traffic via SNMP and displays real-time bandwidth usage on analog gauges using PWM signals.

## Overview

The system polls a router via SNMP to get network interface statistics, calculates upload/download rates, and drives analog meters to provide a visual representation of network activity.

## Hardware Requirements

- Raspberry Pi with GPIO capabilities
- Analog meters (3V maximum input)
- OR Arduino with network connectivity
- Router with SNMP enabled

## Software Components

### gauge.py (Main Script - Raspberry Pi)
The primary monitoring script that uses Raspberry Pi GPIO to drive analog meters directly.

**Features:**
- SNMP polling of router interface statistics
- Real-time rate calculation with 2-second sampling interval
- PWM output scaled for 3V analog meters
- Configurable uplink (40 Mbps) and downlink (1 Gbps) scaling
- Verbose mode for debugging

**Usage:**
```bash
python3 gauge.py          # Normal mode
python3 gauge.py -v       # Verbose mode with detailed output
```

**GPIO Pins:**
- GPIO13: Uplink meter
- GPIO18: Downlink meter

### m3.py (Alternative Implementation)
Similar to gauge.py but uses gpiozero library instead of RPi.GPIO.

**Key Differences:**
- Uses `PWMOutputDevice` from gpiozero
- Includes interface table discovery function
- 0.5 second sampling interval (may cause alternating readings)

### m4.py (Arduino Version)
Network-based version that sends PWM commands to an Arduino over HTTP.

**Features:**
- HTTP requests to Arduino at configured IP address
- Arduino controls D5 (uplink) and D3 (downlink) pins
- 2-second sampling interval

## Configuration

### Router Settings
Update these variables in the scripts:
```python
router_ip = '204.128.136.11'        # Router IP address
community = 'phfactor.net'          # SNMP community string  
interface_index = 3                 # Interface index (usually WAN)
```

### Scaling Limits
```python
up_max = 5_000_000      # 40 Mbps uplink = 5 MB/s
down_max = 500_000_000  # Burst capacity = 500 MB/s
```

## SNMP Details

The scripts use these OIDs:
- `ifInOctets` (1.3.6.1.2.1.31.1.1.1.6.{index}): Bytes received
- `ifOutOctets` (1.3.6.1.2.1.31.1.1.1.10.{index}): Bytes transmitted

**Important Notes:**
- Uses 64-bit counters (ifHC) to handle high-speed interfaces
- 2-second sampling matches most router SNMP update intervals
- Handles counter wrapping for long-running monitoring

## Installation

1. Install required Python packages:
```bash
pip3 install pysnmp RPi.GPIO gpiozero requests
```

2. Enable SNMP on your router with appropriate community string

3. Configure GPIO permissions for Pi user:
```bash
sudo usermod -a -G gpio pi
```

4. Run the monitoring script:
```bash
python3 gauge.py
```

## Troubleshooting

### Common Issues

**PWM Duty Cycle Errors:**
- Ensure max values are set appropriately for your connection speed
- PWM values are clamped to 0-100 range

**Alternating High/Zero Readings:**
- Use 2-second sampling interval to match router SNMP updates
- Check if your router supports 1-second SNMP counter updates

**Incorrect Direction:**
- Verify interface perspective: router WAN interface shows
  - `ifInOctets`: Your uplink traffic (to internet)
  - `ifOutOctets`: Your downlink traffic (from internet)

**High Readings After Traffic Stops:**
- Disable or reduce exponential smoothing (set alpha = 1.0)
- Check sampling interval matches router update frequency

### Debug Mode
Use verbose mode to troubleshoot:
```bash
python3 gauge.py -v
```

This shows:
- Raw SNMP values
- Calculated rates  
- PWM scaling values
- Smoothed results

## Hardware Notes

- Analog meters rated for 3V maximum (not 3.3V)
- PWM scaling: `(3.0/3.3) = 0.909` factor applied
- GPIO pins use 100Hz PWM frequency for smooth needle movement

## Rate Publishing

Each sample is atomically written to `/run/netrate` as:

```
down_Bps up_Bps down_max_Bps up_max_Bps epoch
```

Consumers treat data older than ~10 seconds as stale. The fleet-wide
`sysfetch` login greeting renders these as Net Down / Net Up bars.

### TCP export

`netrate.socket` + `netrate@.service` (systemd socket activation) serve
the current sample to LAN clients — `nc netmon 8378` — restricted to
204.128.136.0/24. Install:

```bash
sudo cp netrate.socket netrate@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now netrate.socket
```

## License

This project is for educational and monitoring purposes. Ensure SNMP access complies with your network policies.