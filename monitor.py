from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
import time

def get_snmp_octets(router_ip, community, interface_index):
    oids = {
        'ifInOctets': f'1.3.6.1.2.1.2.2.1.10.{interface_index}',
        'ifOutOctets': f'1.3.6.1.2.1.2.2.1.16.{interface_index}'
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
    """Scale throughput to 8-bit PWM (0–255)."""
    value = min(value_bps / max_bps, 1.0)  # Clamp to max
    return int(value * 255)


def get_network_throughput(router_ip, community, interface_index, interval=5):
    in_octets1, out_octets1 = get_snmp_octets(router_ip, community, interface_index)
    time.sleep(interval)
    in_octets2, out_octets2 = get_snmp_octets(router_ip, community, interface_index)

    uplink_bps = ((out_octets2 - out_octets1) * 8) / interval
    downlink_bps = ((in_octets2 - in_octets1) * 8) / interval

    return uplink_bps, downlink_bps

# Example usage:
router_ip = '204.128.136.11'
community = 'phfactor.net'
interface_index = 3  # interface index to monitor

uplink, downlink = get_network_throughput(router_ip, community, interface_index)
print(f'Uplink: {uplink:.2f} bps, Downlink: {downlink:.2f} bps')
