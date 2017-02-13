#!/bin/bash
cd /root/WebConfigServer
source linuxenv/bin/activate
pkill -9 -f main.py
pkill -9 -f APSync
#service supervisor restart

