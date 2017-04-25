#!/usr/bin/python
# this is a linux-specific script, despite being in python - buzz.
#  it purpose is to be triggeded on-boot  (See on_reboot.sh ), and re-write the hostapd.conf file to have the current
# device MAC address in it.    NOTE:  this is the MAC of eth0, the pyhsical WIRED  ethernet , not any of the wireless module/s. 
#   We also  write the MAC in question to  my_mac_serial.json in /persist etc ) 

import re
import subprocess
import time
import os
import sys

if sys.platform == 'win32':
    rootfolder = 'X:\\WebConfigServer\\'
    toolsfolder = rootfolder+'tools\\'
else:
    rootfolder = '/root/WebConfigServer/'
    toolsfolder = rootfolder+'tools/'
sys.path.append(rootfolder)
#sys.path.append(folder)
from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config,read_my_mac_address,write_my_mac_address

# find it from the OS, and write it to a file, done!. 
m =  write_my_mac_address()

WLAN1SSID = 'APSync-'+m

#print WLAN1SSID

if sys.platform == 'win32':
    print "SORRY: cant edit actual hostapd.conf on windows, modding local copy as demo instead...."
    #sys.exit()
    interfacesfile = toolsfolder+'hostapd.conf'
else:
    interfacesfile = '/etc/hostapd/hostapd.conf'

interfacescontent = '''
interface=wlan1
driver=nl80211
ssid='''+WLAN1SSID+'''
hw_mode=g
channel=11
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=securepasswords
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
'''

# create new:
file_put_contents(interfacesfile,interfacescontent)

## restart service.
#cmd1 = 'service hostapd restart 2>/dev/null >/dev/null ;'
#print cmd1
#if sys.platform == 'win32':
#    print "windows can't do that... skipped it here"
#else:
#    #ret = subprocess.call(cmd1,shell=True,stdout=open('/dev/null', 'w'),stderr=open('/dev/null', 'w'))
#    ret = subprocess.call(cmd1,shell=True,stderr=subprocess.STDOUT)


# send a msg to any one/thing that might be listening or logging things. 
resultfile = rootfolder+'cronqueue/hostapd.json.done'	
resultmsg = '''
{
  "_target": "logging",
  "data": {"HOSTAPD_UPDATE": {"status": "OK" }}
}
'''

file_put_contents(resultfile,resultmsg)
