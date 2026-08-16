from gpiozero import PWMOutputDevice
from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity, nextCmd
import time

# Configuration
UPLINK_PIN = 13  # GPIO13
DOWNLINK_PIN = 18  # GPIO18
router_ip = '204.128.136.11'
community = 'phfactor.net'
interface_index = 3
interval = 0.5  # seconds between samples (2Hz)

# Scale thresholds
UPLINK_MAX_BPS = 40_000_000     # 40 Mbps
DOWNLINK_MAX_BPS = 1_000_000_000  # 1 Gbps

# Track smoothed values
smoothed_uplink = 0
smoothed_downlink = 0

# Initialize PWM outputs
uplink_meter = PWMOutputDevice(UPLINK_PIN)
downlink_meter = PWMOutputDevice(DOWNLINK_PIN)

def get_snmp_octets(router_ip, community, interface_index):
    oids = {
        'ifInOctets': f'1.3.6.1.2.1.31.1.1.1.6.{interface_index}',
        'ifOutOctets': f'1.3.6.1.2.1.31.1.1.1.10.{interface_index}'
    }

    octets = {}

    for key, oid in oids.items():
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            UdpTransportTarget((router_ip, 161)),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )

        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

        if errorIndication:
            raise Exception(errorIndication)
        elif errorStatus:
            raise Exception(f'{errorStatus.prettyPrint()} at {errorIndex}')
        else:
            for varBind in varBinds:
                octets[key] = int(varBind[1])

    return octets['ifInOctets'], octets['ifOutOctets']

def scale_to_pwm(value_bps, max_bps):
    if value_bps < 0 or value_bps > (max_bps * 1.2):
        return 0
    return min(value_bps / max_bps, 1.0) * (3.0 / 3.3)

def print_interface_table(router_ip, community):
    print('SNMP Interface Table:')
    for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        UdpTransportTarget((router_ip, 161)),
        ContextData(),
        ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.2'))  # ifDescr
    ):
        if errorIndication:
            print(f'Error: {errorIndication}')
            break
        elif errorStatus:
            print(f'Error: {errorStatus.prettyPrint()} at {errorIndex}')
            break
        else:
            for varBind in varBinds:
                print(f'{varBind[0]} = {varBind[1]}')

def monitor_and_update():
    global smoothed_uplink, smoothed_downlink

    in1, out1 = get_snmp_octets(router_ip, community, interface_index)
    print(f'Raw SNMP before: in1={in1}, out1={out1}')
    time.sleep(interval)
    in2, out2 = get_snmp_octets(router_ip, community, interface_index)
    print(f'Raw SNMP after:  in2={in2}, out2={out2}')

    uplink_bps = ((in2 - in1) * 8) / interval if in2 >= in1 else 0
    downlink_bps = ((out2 - out1) * 8) / interval if out2 >= out1 else 0

    # Exponential smoothing - increased alpha for faster response
    alpha = 0.4  # Increased from 0.2 for faster response at 2Hz
    smoothed_uplink = (1 - alpha) * smoothed_uplink + alpha * uplink_bps
    smoothed_downlink = (1 - alpha) * smoothed_downlink + alpha * downlink_bps

    uplink_pwm = scale_to_pwm(smoothed_uplink, UPLINK_MAX_BPS)
    downlink_pwm = scale_to_pwm(smoothed_downlink, DOWNLINK_MAX_BPS)

    uplink_MBps = smoothed_uplink / 8 / 1_000_000
    downlink_MBps = smoothed_downlink / 8 / 1_000_000

    print(f"Uplink: {uplink_MBps:.2f} MB/s → PWM {uplink_pwm:.3f}")
    print(f"Downlink: {downlink_MBps:.2f} MB/s → PWM {downlink_pwm:.3f}")

    # Update PWM outputs
    uplink_meter.value = uplink_pwm
    downlink_meter.value = downlink_pwm

if __name__ == "__main__":
    print_interface_table(router_ip, community)
    try:
        while True:
            monitor_and_update()
    except KeyboardInterrupt:
        # Clean up GPIO on exit
        uplink_meter.close()
        downlink_meter.close()
