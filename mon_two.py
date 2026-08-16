import time
import requests
from pysnmp.hlapi import *


def get_snmp_octets(router_ip, community, interface_index):
    oids = {
        'ifInOctets': f'1.3.6.1.2.1.31.1.1.1.6.{interface_index}',
        'ifOutOctets': f'1.3.6.1.2.1.31.1.1.1.10.{interface_index}'
    }
    result = {}
    for name, oid in oids.items():
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
            result[name] = int(varBinds[0][1])

    return result['ifInOctets'], result['ifOutOctets']

def scale_to_pwm(value_bps, max_bps):
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

def monitor_and_update(router_ip, community, interface_index, arduino_ip, interval=5):
    in1, out1 = get_snmp_octets(router_ip, community, interface_index)
    time.sleep(interval)
    in2, out2 = get_snmp_octets(router_ip, community, interface_index)

    uplink_bps = ((out2 - out1) * 8) / interval
    downlink_bps = ((in2 - in1) * 8) / interval

    # Scale to 0–255
    pwm_uplink = scale_to_pwm(uplink_bps, 40e6)      # 40 Mbps
    pwm_downlink = scale_to_pwm(downlink_bps, 1e9)   # 1 Gbps

    uplink_MBps = uplink_bps / 8 / 1_000_000
    downlink_MBps = downlink_bps / 8 / 1_000_000

    print(f"Uplink: {uplink_MBps:.2f} MB/s → PWM {pwm_uplink}")
    print(f"Downlink: {downlink_MBps:.2f} MB/s → PWM {pwm_downlink}")
    send_pwm_value(arduino_ip, 5, pwm_uplink)   # D5 = uplink
    send_pwm_value(arduino_ip, 3, pwm_downlink) # D3 = downlink

if __name__ == "__main__":
    router_ip = "204.128.136.11"
    community = "phfactor.net"
    interface_index = 3  # Change this as needed
    arduino_ip = "204.128.136.20"  # Your RESTduino IP

    while True:
        monitor_and_update(router_ip, community, interface_index, arduino_ip, interval=2)    