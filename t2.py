from gpiozero import PWMOutputDevice
from time import sleep

meter1 = PWMOutputDevice(18)  # GPIO18, pin 12
meter2 = PWMOutputDevice(13)  # GPIO13, pin 33

# Example: Sweep both meters
for dc in range(0, 101, 10):
    meter1.value = dc / 100
    meter2.value = (100 - dc) / 100
    sleep(0.5)
