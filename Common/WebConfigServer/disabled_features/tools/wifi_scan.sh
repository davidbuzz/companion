#!/bin/bash
# SAVE LIST TO A FILE
/sbin/iwlist wlan0 scan | /bin/grep SSID | cut -c 27-80  | grep -vi apsync
sleep 1
# QUIETLY EXECUTE SCRIPT THAT SENDS LIST TO BROWSER.
cd /root/WebConfigServer/  2>&1 > /dev/null
source linuxenv/bin/activate 2>&1 > /dev/null
python ./tools/wifis_available.py 2>&1 > /dev/null