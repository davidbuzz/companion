#!/bin/bash
# things we do on reboot....
# this ensures the WLAN1 SSID has a MAC address in it unique to the machine...

# early non-networking related things...
touch /tmp/125 &
touch /tmp/udhcpd.leases
touch /var/log/lastlog

# enable the script/s that manage the reset button and turn the LEDs on and off as early as possible. ( its not network dependant )
cp /persist/leds.json /tmp/leds.json
cd /root/WebConfigServer
/root/WebConfigServer/linuxenv/bin/python ./tools/gpio_button.py  2>&1 > /dev/null &
cd /root/WebConfigServer
/root/WebConfigServer/linuxenv/bin/python ./tools/gpio_led.py  2>&1 > /dev/null &

echo "on_reboot.sh script waiting now" > /dev/console

# load wifi drivers manually, and in correct order, ASAP.  
/root/WebConfigServer/tools/start_wifi_drivers.sh 

sleep 5 # important to delay this script till the minimal interfaces and driver bring-up is done 

echo "on_reboot.sh script starts now" > /dev/console


# we write this before networking comes up too
cd /root/WebConfigServer
/root/WebConfigServer/linuxenv/bin/python ./tools/write_hostapd_conf.py ; echo "written hostapd.conf" > /dev/console

ifup wlan1 ;  echo "bringing wlan1 (down then) up" > /dev/console
if [ -n "`ifconfig wlan1 | grep 10.10.10.1`" ] ; then
	echo "10.10.10.1 found ok"
else
	echo "10.10.10.1 not found, retrying..."
	ifdown wlan1; ifup wlan1 ;  echo "bringing wlan1 up again" > /dev/console
fi

# we now start AND stop hostapd in the pre-up and post-up clause in /etc/network/interfaces, created by do_interfaces_file()
#service hostapd stop ; pkill -9 hostapd ; echo "hostapd killed" > /dev/console
#sleep 1 ; service hostapd start ;
#/usr/sbin/hostapd -d -P /run/hostapd.pid /persist/hostapd.conf > /persist/hostapd.log &
#echo "hostapd re-started" > /dev/console

service udhcpd stop ; pkill -9 udhcpd ; sleep 1 ; service udhcpd start > /dev/console
echo "udhcpd kill and start" > /dev/console

sleep 1
if [ -n "`ps auxww | grep udhcpd | grep -v grep`" ] ; then
	echo "udhcpd found running ok"
else
	echo "udhcpd not found, retrying..."
	/usr/sbin/udhcpd -S ; echo "udhcpd re-start" > /dev/console
fi

# poke each of the possible WIFI interfacces, and test each till we get one that works.... or eth0 if desperate..
cd /root/WebConfigServer
/root/WebConfigServer/linuxenv/bin/python tools/wifitest.py > /dev/console
echo "wifitest.py execution complete" > /dev/console

ntpdate -u pool.ntp.org ; service ntp stop ; pkill -9 ntpd ; sleep 1 ; service ntp start > /dev/console
echo "ntpdate and ntpd kill and start" > /dev/console

# and  this populates the data for the webpage that reads this later.
/root/WebConfigServer/tools/wifi_scan.sh > /root/WebConfigServer/tools/wifi_scan.txt 2>&1 


touch /tmp/126 &
