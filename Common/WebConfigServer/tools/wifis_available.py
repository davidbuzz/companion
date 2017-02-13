#!/usr/bin/python
# this is a linux-specific script, despite being in python - buzz.
#  it purpose is to populate the list of available wifis in the web interfacem, near the "test wifi" button, 

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
from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config

if sys.platform == 'win32':
    dirname = 'X:\\WebConfigServer\\tools\\'
    dirname2 = 'X:\\WebConfigServer\\cronqueue\\'
    filename = dirname+'wifi_scan.txt'
else:
    dirname = '/root/WebConfigServer/tools/'
    dirname2 = '/root/WebConfigServer/cronqueue/'
    filename = dirname+'wifi_scan.txt'

#data = file_get_contents(file)
mylist = []
with open(filename,'r') as f:
    for x in f:
        x = x.rstrip()
        x = x.lstrip()
        if not x: continue  
        #(title,value) = x.split(":")
        if x.startswith('"') and x.endswith('"'):
            x = x[1:-1]   # drop leading and trailing quote chars we know are there
        mylist.append(x)


resultfile = dirname2+'wifilistresult.json.done'
resultfile2 = dirname2+'wifilistresult.json'

#avail = str(mylist)
#print avail

# send to browser and logger...
resultmsg = '''
{
  "_target": "logging",
  "data": {
    "WIFIAVAILABLE": []
  }
}
'''

j = json.loads(resultmsg)
j['data']['WIFIAVAILABLE'] = mylist
cleaned = json.dumps(j) 

def touch(fname, times=None):
    with open(fname, 'a'):
        os.utime(fname, times)

file_put_contents(resultfile,cleaned)

touch(resultfile2)
os.unlink(resultfile2)
os.rename(resultfile,resultfile2)

