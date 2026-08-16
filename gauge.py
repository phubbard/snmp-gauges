import RPi.GPIO as GPIO
import time
from pysnmp.hlapi import *
import math
import sys

class NetworkMeter:
    def __init__(self, pin, max_value, oid):
        self.pin = pin
        self.max_value = max_value
        self.oid = oid
        GPIO.setup(pin, GPIO.OUT)
        self.pwm = GPIO.PWM(pin, 100)  # 100Hz frequency
        self.pwm.start(0)

    def set_pwm(self, value):
        self.pwm.ChangeDutyCycle(value)

    def cleanup(self):
        self.pwm.stop()

class NetworkMonitor:
    def __init__(self, verbose=False):
        # Initialize GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # SNMP OIDs for network interface statistics
        self.oids = {
            'ifInOctets': '1.3.6.1.2.1.31.1.1.1.6.9',  # ifHCInOctets for eth4 (index 9)
            'ifOutOctets': '1.3.6.1.2.1.31.1.1.1.10.9'  # ifHCOutOctets for eth4 (index 9)
        }

        # Maximum values for scaling (in bytes per second)
        self.up_max = 5_000_000      # 40 Mbps uplink = 5 MB/s
        self.down_max = 150_000_000  # 1.2 Gbps downlink = 150 MB/s

        # Minimum detectable rate (bytes/sec) - below this, gauge reads zero
        # 1 KB/s is background noise level
        self.rate_floor = 1000

        # Initialize meters
        self.up_meter = NetworkMeter(13, self.up_max, self.oids['ifOutOctets'])  # GPIO13 for upload
        self.down_meter = NetworkMeter(18, self.down_max, self.oids['ifInOctets'])  # GPIO18 for download

        # Store previous SNMP values for rate calculation
        self.prev_up_value = None
        self.prev_down_value = None
        self.prev_time = None

        # Exponential smoothing parameters
        self.alpha = 1.0  # No smoothing - immediate response
        self.smoothed_up_rate = 0
        self.smoothed_down_rate = 0

        # Verbose mode flag
        self.verbose = verbose

    def get_snmp_value(self, oid):
        """Get SNMP value from remote device"""
        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                  CommunityData('phfactor.net', mpModel=1),  # SNMPv2c
                  UdpTransportTarget(('204.128.136.11', 161)),
                  ContextData(),
                  ObjectType(ObjectIdentity(oid)))
        )

        if errorIndication:
            print(f"Error: {errorIndication}")
            return 0
        elif errorStatus:
            print(f"Error: {errorStatus.prettyPrint()} at {varBinds[int(errorIndex)-1][0] if errorIndex else '?'}")
            return 0
        else:
            for varBind in varBinds:
                value = int(varBind[1])
                if self.verbose:
                    print(f"SNMP OID {oid} returned value: {value}")
                return value

    def scale_to_pwm(self, value_bps, max_bps):
        """Scale bytes/sec to PWM value (0-100) using logarithmic scaling.

        Log scaling makes low traffic visible on the gauge while still
        reaching full scale at max ISP speed. The log range spans from
        rate_floor to max_bps.
        """
        if value_bps <= self.rate_floor:
            return 0

        if value_bps >= max_bps:
            return min(int(100 * (3.0 / 3.3)), 100)

        # Logarithmic scaling: map log(value) within [log(floor), log(max)] to [0, max_pwm]
        log_floor = math.log(self.rate_floor)
        log_max = math.log(max_bps)
        log_val = math.log(value_bps)

        fraction = (log_val - log_floor) / (log_max - log_floor)
        pwm_value = int(fraction * 100 * (3.0 / 3.3))

        return max(0, min(pwm_value, 100))

    def run(self):
        """Main loop to update meters"""
        last_print_time = time.time()
        while True:
            try:
                # Get current values from SNMP
                up_value = self.get_snmp_value(self.oids['ifOutOctets'])  # Value is in bytes
                down_value = self.get_snmp_value(self.oids['ifInOctets'])  # Value is in bytes

                if self.verbose:
                    print(f"Raw SNMP values - Up: {up_value}, Down: {down_value}")

                current_time = time.time()

                # Skip the first reading
                if self.prev_up_value is None or self.prev_down_value is None:
                    self.prev_up_value = up_value
                    self.prev_down_value = down_value
                    self.prev_time = current_time
                    time.sleep(1)
                    continue

                # Calculate elapsed time
                elapsed = current_time - self.prev_time

                # Calculate rate in bytes per second, handling counter wrapping
                if up_value < self.prev_up_value:
                    up_delta = (up_value + (2**64) - self.prev_up_value) % (2**64)
                else:
                    up_delta = up_value - self.prev_up_value

                if down_value < self.prev_down_value:
                    down_delta = (down_value + (2**64) - self.prev_down_value) % (2**64)
                else:
                    down_delta = down_value - self.prev_down_value

                up_rate = up_delta / elapsed
                down_rate = down_delta / elapsed

                # Update previous values
                self.prev_up_value = up_value
                self.prev_down_value = down_value
                self.prev_time = current_time

                # Apply exponential smoothing
                self.smoothed_up_rate = (1 - self.alpha) * self.smoothed_up_rate + self.alpha * up_rate
                self.smoothed_down_rate = (1 - self.alpha) * self.smoothed_down_rate + self.alpha * down_rate

                # Calculate PWM values (0-100)
                up_pwm = self.scale_to_pwm(self.smoothed_up_rate, self.up_max)
                down_pwm = self.scale_to_pwm(self.smoothed_down_rate, self.down_max)

                if self.verbose:
                    up_rate_mb = self.smoothed_up_rate / 1_000_000
                    down_rate_mb = self.smoothed_down_rate / 1_000_000
                    print(f"Up: {up_rate_mb:.3f} MB/s (PWM {up_pwm}%), Down: {down_rate_mb:.3f} MB/s (PWM {down_pwm}%)")

                # Update meters
                self.up_meter.set_pwm(up_pwm)
                self.down_meter.set_pwm(down_pwm)

                # Print summary every 30 seconds in non-verbose mode
                if not self.verbose:
                    if current_time - last_print_time >= 30:
                        up_rate_mb = self.smoothed_up_rate / 1_000_000
                        down_rate_mb = self.smoothed_down_rate / 1_000_000
                        print(f"Up: {up_rate_mb:.3f} MB/s (PWM {up_pwm}%), Down: {down_rate_mb:.3f} MB/s (PWM {down_pwm}%)")
                        last_print_time = current_time

                # 1-second update interval
                time.sleep(1)

            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(1)

    def cleanup(self):
        """Clean up GPIO resources"""
        self.up_meter.cleanup()
        self.down_meter.cleanup()
        GPIO.cleanup()

if __name__ == '__main__':
    verbose = '-v' in sys.argv
    try:
        monitor = NetworkMonitor(verbose=verbose)
        monitor.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        monitor.cleanup()
    except Exception as e:
        print(f"Error: {e}")
        if 'monitor' in locals():
            monitor.cleanup()
