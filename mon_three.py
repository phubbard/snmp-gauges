from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
import time
import requests

# Configuration
router_ip = '204.128.136.11'
community = 'phfactor.net'
interface_index = 3
arduino_ip = '204.128.136.20'
interval = 2  # seconds between samples

# Scale thresholds
UPLINK_MAX_BPS = 40_000_000     # 40 Mbps
DOWNLINK_MAX_BPS = 1_000_000_000  # 1 Gbps

# Track smoothed values
smoothed_uplink = 0
smoothed_downlink = 0

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
    return int(min(value_bps / max_bps, 1.0) * 255)

def send_pwm_value(arduino_ip, pin, value):
    url = f"http://{arduino_ip}/D{pin}/{value}"
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            print(f"Set D{pin} to {value}")
        else:
            print(f"Failed to set D{pin}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error contacting Arduino: {e}")

def monitor_and_update():
    global smoothed_uplink, smoothed_downlink

    in1, out1 = get_snmp_octets(router_ip, community, interface_index)
    time.sleep(interval)
    in2, out2 = get_snmp_octets(router_ip, community, interface_index)

    uplink_bps = ((out2 - out1) * 8) / interval if out2 >= out1 else 0
    downlink_bps = ((in2 - in1) * 8) / interval if in2 >= in1 else 0

    # Exponential smoothing
    alpha = 0.2
    smoothed_uplink = (1 - alpha) * smoothed_uplink + alpha * uplink_bps
    smoothed_downlink = (1 - alpha) * smoothed_downlink + alpha * downlink_bps

    uplink_pwm = scale_to_pwm(smoothed_uplink, UPLINK_MAX_BPS)
    downlink_pwm = scale_to_pwm(smoothed_downlink, DOWNLINK_MAX_BPS)

    uplink_MBps = smoothed_uplink / 8 / 1_000_000
    downlink_MBps = smoothed_downlink / 8 / 1_000_000

    print(f"Uplink: {uplink_MBps:.2f} MB/s → PWM {uplink_pwm}")
    print(f"Downlink: {downlink_MBps:.2f} MB/s → PWM {downlink_pwm}")

    send_pwm_value(arduino_ip, 5, uplink_pwm)   # D5 = uplink
    send_pwm_value(arduino_ip, 3, downlink_pwm) # D3 = downlink

if __name__ == "__main__":
    while True:
        monitor_and_update()
