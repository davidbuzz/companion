#!/bin/bash
pkill -f main.py
pkill -f APSync
sleep 1 
pkill -9 -f main.py
pkill -9 -f APSync
cd /root/WebConfigServer
source linuxenv/bin/activate
exec /root/WebConfigServer/linuxenv/bin/python main.py 2>&1  > /dev/null
