 #!/bin/bash
 #
 # don't forget to chmod 755 this file, as it's important for ifup to be able to run it. 
 #
/usr/bin/pkill -9 -f hostapd || true
/usr/sbin/rfkill unblock 1 || true
sleep 1
/usr/sbin/hostapd -d -P /run/hostapd2.pid /persist/hostapd.conf || true

#       post-down /usr/bin/pkill -9 -f hostapd || true
#       post-down /usr/sbin/rfkill unblock 1 || true
       #/usr/bin/python /persist/runme.py || true


 