#!/bin/bash
cd /root/WebConfigServer
service supervisor stop
source linuxenv/bin/activate
pkill -9 -f main.py
pkill -9 -f APSync
python main.py