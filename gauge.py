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
            'ifInOctets': '1.3.6.1.2.1.31.1.1.1.6.3',  # ifHCInOctets for eth0 (index 3)
            'ifOutOctets': '1.3.6.1.2.1.31.1.1.1.10.3'  # ifHCOutOctets for eth0 (index 3)
        }

        # Maximum values for scaling (in bits per second)
        self.up_max = 40_000_000    # 40 Mbps uplink in bits/sec
        self.down_max = 125_000_000  # 1 Gbps downlink in bits/sec

        # Initialize meters
        self.up_meter = NetworkMeter(18, self.up_max, self.oids['ifOutOctets'])  # GPIO18 for upload
        self.down_meter = NetworkMeter(13, self.down_max, self.oids['ifInOctets'])  # GPIO13 for download

        # Store previous SNMP values for rate calculation
        self.prev_up_value = None
        self.prev_down_value = None

        # Exponential smoothing parameters
        self.alpha = 0.8  # Increased smoothing factor for faster response
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
        """Scale bits per second to PWM value (0-100) using logarithmic scaling for high values"""
        if value_bps < 0:
            print(f"Warning: Value {value_bps} is negative")
            return 0

        # Set minimum threshold for PWM
        min_threshold = max_bps * 0.01  # 1% of max

        # For very large values, use a logarithmic scale
        if value_bps > max_bps:
            log_value = math.log(value_bps / max_bps, 10)
            pwm_value = min(100 - int((math.exp(log_value) - 1) * 50), 100)
        elif value_bps > min_threshold:
            # For values above threshold but below max, use linear scaling
            pwm_value = int(min(value_bps / max_bps, 1.0) * 100)
        else:
            # For values below threshold, set PWM to 0
            pwm_value = 0

        return pwm_value

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

                # Skip the first reading
                if self.prev_up_value is None or self.prev_down_value is None:
                    self.prev_up_value = up_value
                    self.prev_down_value = down_value
                    time.sleep(1)
                    continue

                # Calculate rate (delta) in bytes per second, handling counter wrapping
                if up_value < self.prev_up_value:
                    up_rate = (up_value + (2**64) - self.prev_up_value) % (2**64)  # Handle 64-bit counter wrap
                else:
                    up_rate = up_value - self.prev_up_value

                if down_value < self.prev_down_value:
                    down_rate = (down_value + (2**64) - self.prev_down_value) % (2**64)  # Handle 64-bit counter wrap
                else:
                    down_rate = down_value - self.prev_down_value

                if self.verbose:
                    print(f"Calculated rates - Up: {up_rate}, Down: {down_rate}")

                # Update previous values
                self.prev_up_value = up_value
                self.prev_down_value = down_value

                # Apply exponential smoothing with increased alpha
                self.smoothed_up_rate = (1 - self.alpha) * self.smoothed_up_rate + self.alpha * up_rate
                self.smoothed_down_rate = (1 - self.alpha) * self.smoothed_down_rate + self.alpha * down_rate

                if self.verbose:
                    print(f"Smoothed rates - Up: {self.smoothed_up_rate}, Down: {self.smoothed_down_rate}")

                # Convert to Mb/sec for display
                up_rate_mb = self.smoothed_up_rate / 1000000
                down_rate_mb = self.smoothed_down_rate / 1000000

                if self.verbose:
                    print(f"Rates in MB/s - Up: {up_rate_mb}, Down: {down_rate_mb}")

                # Calculate PWM values (0-100)
                up_pwm = self.scale_to_pwm(self.smoothed_up_rate, self.up_max)
                down_pwm = self.scale_to_pwm(self.smoothed_down_rate, self.down_max)

                if self.verbose:
                    print(f"PWM values - Up: {up_pwm}, Down: {down_pwm}")

                # Update meters
                self.up_meter.set_pwm(up_pwm)
                self.down_meter.set_pwm(down_pwm)

                # Print summary every minute in non-verbose mode
                if not self.verbose:
                    current_time = time.time()
                    if current_time - last_print_time >= 60:
                        print(f"Rates in MB/s - Up: {up_rate_mb:.2f}, Down: {down_rate_mb:.2f}")
                        last_print_time = current_time

                # Sleep for 1 second
                time.sleep(1)

            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(1)  # Still sleep on error to prevent tight loop

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
