#!/usr/bin/python
# this is the regularly scheduled cron script that is run at a schedule as defined in WebConfigServer.json, and as enforced in the crontab by croneditor.py
#
import json
import sys
import time
import os
import setproctitle


if sys.platform == 'win32':
    dirname = 'X:\\WebConfigServer\\cronqueue\\'
    e = 'X:\\WebConfigServer'
else:
    dirname = '/root/WebConfigServer/cronqueue/'
    e = '/root/WebConfigServer'

sys.path.append(e)

from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config
from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping,log_to_file

packet = { "HighAlert": [ "ff:ff:ff:ff:ff:ff" ], "other": "by heartbeat.py CRON" }
go1 = json_wrap_with_target(packet,'serialpacket')
go2 = json_wrap_with_target(packet,'logging')
file_put_contents(dirname+'go1heartbeat.json',go1)
file_put_contents(dirname+'go2heartbeat.json',go2)
print "go1heartbeat.json created: " + go1
print "go2heartbeat.json created: " + go2

print "waiting here for 60 seconds for all responses to come in"
time.sleep(60)

packet = { "AllClear": [ "ff:ff:ff:ff:ff:ff" ], "other": "by heartbeat.py CRON" }
go3 = json_wrap_with_target(packet,'serialpacket')
go4 = json_wrap_with_target(packet,'logging')
file_put_contents(dirname+'go1heartbeat.json',go3)
file_put_contents(dirname+'go2heartbeat.json',go4)
print "go3heartbeat.json created: " + go3
print "go4heartbeat.json created: " + go4

print "waiting here for 10 seconds for it to be handled..."
time.sleep(10)

# NOW WE DO THE ACTUAL THING WE CAME HERE FOR... 

packet = { "DeviceUpdateRequest": [ "ff:ff:ff:ff:ff:ff" ], "other": "by heartbeat.py CRON" }
go5 = json_wrap_with_target(packet,'serialpacket')
go6 = json_wrap_with_target(packet,'logging')
file_put_contents(dirname+'go1heartbeat.json',go5)
file_put_contents(dirname+'go2heartbeat.json',go6)
print "go5heartbeat.json created: " + go5
print "go6heartbeat.json created: " + go6


# cleanup any possibles..
try:
    ##os.unlink(dirname+'goheartbeat.json');
    #os.unlink(dirname+'goheartbeat.json.done');
    ##os.unlink(dirname+'stopheartbeat.json');
    #os.unlink(dirname+'stopheartbeat.json.done');
    ##os.unlink(dirname+'goheartbeat2.json');
    #os.unlink(dirname+'goheartbeat2.json.done');
    ##os.unlink(dirname+'stopheartbeat2.json');
    #os.unlink(dirname+'stopheartbeat2.json.done');
    pass
except BaseException as e:
    # don't care if unlinks fail, just move on.
    pass

print "done."

