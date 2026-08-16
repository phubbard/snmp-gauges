from gpiozero import PWMOutputDevice
from time import sleep

meter = PWMOutputDevice(18)  # GPIO18 (pin 12)

# Set to 50% duty (2.5V out if 5V logic level)
meter.value = 0.5
sleep(5)

# Full scale (5V)
meter.value = 1.0
sleep(5)

# Zero
meter.value = 0.0
