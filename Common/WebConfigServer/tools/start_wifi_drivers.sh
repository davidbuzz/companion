# load drivers in a consistent order that always loads the built-in hardware driver FIRST so it's wlan0, THEN try the other/s for wlan1

# builtin wifi:
modprobe brcmfmac
# WiPi usb dongle:
modprobe rt2800usb
# other dongle: 
#modprobe r8188eu
