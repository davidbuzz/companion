#!/usr/bin/python
# this is a linux-specific script, despite being in python - buzz.
#  it purpose is to be run from CRON ( not the web interface ) login to the given wifi credentials ( ssid1, pwd1 ) 
# and then try to ping google through the new route.   if it's successful, it leaves the route in-place, otherwise it tries the other crednetials and repeats.
# if it fails to connect to *either* of them ( neither work ), it then also tries to route out via eth0, as that might be connected too...
#
# DO NOT trigger this from inside the thread/s of the main.py or cron_reader etc, as it's NOT designed to work from there.
# MUST be called from on-boot script only...  see on_reboot.sh

import re
import subprocess
import time
import os
import sys
import json

if sys.platform == 'win32':
    e = 'X:\\WebConfigServer'
else:
    e = '/root/WebConfigServer'
sys.path.append(e)
from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config,write_new_master,do_interfaces_file,read_master_wifi,change_leds


if sys.platform == 'win32':
    print "wifitest.py was started OK, but it can't do anything on windows"
    sys.exit()

def ping(ip):
        print "Pinging %s" % (ip)
        ret = subprocess.call("ping -c 2 -I wlan0 %s" % ip,
                        shell=True,
                        stdout=open('/dev/null', 'w'),
                        stderr=subprocess.STDOUT)
        if ret == 0:
            print "%s: is alive" % ip
        else:
            print "%s: did not respond" % ip


        return ret

#  this writes to the CRON queue a file at the start of each stage, just so any "watchers" can be made aware...
def emit_stage(stage,shortmsg = "Wifi Test In Progress.....", color = "#66ff33" , stat = "OK"):
    #shortmsg = "Wifi Test In Progress....."
    #stat = "OK"
    #color = "#66ff33"  # green = good
    #stage = 1
    stage_msg = '''
    {
      "_target": "logging",
      "data": {"WIFISTATUS": {"color": "'''+color+'''",  "stage": "'''+str(stage)+'''", "'''+stat+'''": "'''+shortmsg+'''" }}
    }
    '''
    resultfile = '/root/WebConfigServer/cronqueue/wifitestresult.json'	
    file_put_contents(resultfile+".done",stage_msg)
    os.rename(resultfile+".done", resultfile)
    time.sleep(1); # to give time for the file to be picked up by the system.


#  this writes to the CRON queue a file at the end of wifi re-adjustment/s, just so any "watchers" can be made aware...
def emit_new_master(newmaster, stat = "SSID1",shortmsg = "WIFI_CREDENTIALS_CHANGED_TO", color = "#00ff00" ):
    stage_msg = '''
    {
      "_target": "logging",
      "data": {
            "WIFIMASTER": {"color": "'''+color+'''",  "newmaster": "'''+str(newmaster)+'''", "'''+shortmsg+'''": "'''+stat+'''" }
      }
    }
    '''
    resultfile = '/root/WebConfigServer/cronqueue/wifimasterresult.json'	
    file_put_contents(resultfile+".done",stage_msg)
    os.rename(resultfile+".done", resultfile)
    time.sleep(1); # to give time for the file to be picked up by the system.

def touch(fname, times=None):
    with open(fname, 'a'):
        os.utime(fname, times)

if __name__ == '__main__':

    print "WIFITESTER CHECKING EXISTING CONNECTION FIRST"
    vars = read_master_wifi()  # existing master
    # if we are already on a valid credentials, then leave them, and just do a ping of google.
    vars['mssid']
    vars['mpwd']
    # 
    conf = read_config()
    existing = False


    if (vars['mssid'] == conf['ssid1']) and (vars['mpwd'] == conf['pwd1']) :
       decider = 1
       existing = True

    if (vars['mssid'] == conf['ssid2']) and (vars['mpwd'] == conf['pwd2']) :
       decider = 2
       existing = True


    if existing == True:
        # now see if we have a google ping..?  we'll ping it once, via the wlan0, and be sure it's there.
        #ping -I wlan0 -i 1 -c 1 google.com
        ret = ping('8.8.8.8')

        # if alive
        stat = ''
        if ret == 0:
            shortmsg = "The test of the wifi connection went OK!"
            stat = "OK"	
            color = "#66ff33"  # green = good. 
            change_leds(None,1,None)  # green enable
            exit()   # if the ping was good, do nothing, just exist 

        else:
	        shortmsg = "Sorry, the Tested WIFI was unable to be used."
	        stat = "FAIL"
	        color = "#ff6666"   # red = fail.
	        # else if we failed the ping, go to the next section....
	        change_leds(None,0,None)  # green disable
	
        emit_stage( 5,shortmsg,color,stat)
        emit_stage( 6,shortmsg,color,stat)
   
        # don't continue further if we have internet acccess.... just stop here...
        #if ret == 0:
        #    emit_new_master(decider,assid)  # advise browser/user/logs of the change in credentials...
        #    break



    emit_stage(6,color="#ffdb4d")  # default the color of the main block to yellow, firsot.

    deciders = [1,2,1,2]  # wifi1, wifi2

    # each network config to be tried.... 
    for decider in deciders:

        print "WIFITESTER TRYING TO CONNECT TO:"+str(decider)
        assid = write_new_master(decider) # try to use first set of wifi credentials...

        do_interfaces_file() # use the just-written credentials to write the updated /etc/networks/interfaces file

        emit_stage(1)

        print "please wait up-to 30 seconds for wifi to stabilise......"

        cmd1 = 'ifdown wlan0 2>/dev/null >/dev/null'
        print cmd1
        ret = subprocess.call(cmd1,shell=True,stdout=open('/dev/null', 'w'),stderr=open('/dev/null', 'w'))

        emit_stage(2)

        cmd1 = 'ifup wlan0 2>/dev/null >/dev/null'
        print cmd1
        ret = subprocess.call(cmd1,shell=True,stdout=open('/dev/null', 'w'),stderr=open('/dev/null', 'w'))

        emit_stage(3)

        touch('/tmp/dhclient.wlan0.ip')

        # determine potential new route... ( from custom dhclient hook output ) 
        data = file_get_contents('/tmp/dhclient.wlan0.ip')
        datahash = {}
        lines = data.split('\n')
        for l in lines:
            if '=' in l:
                print "line:"+l
                (k,v) = l.split('=')
                datahash[k] = v

        r = '192.168.1.1'
        if 'new_routers' in datahash:
            r = datahash['new_routers']

        print r

        # lets try to route via the wlan if we can.....
        cmd2 = 'iwconfig wlan0 ; ifconfig wlan0 ; route del default ; route add default gw '+r+' wlan0 '
        print cmd2
        ret = subprocess.call(cmd2,shell=True,stderr=subprocess.STDOUT)

        emit_stage(4)

        # now see if we have a google ping..?  we'll ping it once, via the wlan0, and be sure it's there.
        #ping -I wlan0 -i 1 -c 1 google.com
        ret = ping('8.8.8.8')

        # if alive
        stat = ''
        if ret == 0:
            shortmsg = "The test of the wifi connection went OK!"
            stat = "OK"	
            color = "#66ff33"  # green = good. 
            change_leds(None,1,None)  # green enable
        else:
	        shortmsg = "Sorry, the Tested WIFI was unable to be used."
	        stat = "FAIL"
	        color = "#ff6666"   # red = fail.
	        change_leds(None,0,None)  # green disable

	
        emit_stage( 5,shortmsg,color,stat)

        emit_stage( 6,shortmsg,color,stat)
   
        # don't continue further if we have internet acccess.... just stop here...
        if ret == 0:
            emit_new_master(decider,assid)  # advise browser/user/logs of the change in credentials...
            break


        # after test, return routing back to other interface as default:  TODO make this the other WIFI
        #route add default gw 192.168.192.1 eth0 

        ## only if we got a ping from google, leave that as our default route for the moment... 
        #if ret != 0:
        #    # I know the eth0 might not even be up, but if it is, we might as well use it if we don't have ping thru wlan0
        #    # the result of this commmand is that after running this script, the machine will loose its internet route if 
        #    # its not on eth0
        #    cmd4 = 'route del default ; route add default gw '+r+' eth0'
        #    print cmd4
        #    ret = subprocess.call(cmd4,shell=True,stderr=subprocess.STDOUT)

        cmd5 = "service udhcpd restart"
        print cmd5
        ret = subprocess.call(cmd5,shell=True,stderr=subprocess.STDOUT)

        cmd6 = "service ntp restart"
        print cmd6
        ret = subprocess.call(cmd6,shell=True,stderr=subprocess.STDOUT)
    
        cmd6 = "ntpdate -u pool.ntp.org"
        print cmd6
        ret = subprocess.call(cmd6,shell=True,stderr=subprocess.STDOUT)