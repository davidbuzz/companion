cd X:\WebConfigServer\tools

rem plink.exe -pw securepasswords -ssh root@10.10.10.1 "mount / -o remount,rw"
rem plink.exe -pw securepasswords -ssh root@10.10.10.1 "ln -s /tmp /root/WebConfigServer/json"

plink.exe -pw securepasswords -ssh root@10.10.10.1 "mount / -o remount,rw"
plink.exe -pw securepasswords -ssh root@10.10.10.1 "touch /persist/lastminorupdate.txt"
rem plink.exe -pw securepasswords -ssh root@10.10.10.1 "ln -s /tmp /root/WebConfigServer/json"

pscp.exe -pw securepasswords X:\WebConfigServer\*.py root@10.10.10.1:/root/WebConfigServer/
pscp.exe -pw securepasswords X:\WebConfigServer\*.sh root@10.10.10.1:/root/WebConfigServer/

rem copy all the tools folder, except the file we put the uniqie mac address into. 
plink.exe -pw securepasswords -ssh root@10.10.10.1 "cp /root/WebConfigServer/tools/my_mac_serial.json /tmp/my_mac_serial.json"
pscp.exe -pw securepasswords X:\WebConfigServer\tools\* root@10.10.10.1:/root/WebConfigServer/tools/
plink.exe -pw securepasswords -ssh root@10.10.10.1 "cp  /tmp/my_mac_serial.json /root/WebConfigServer/tools/my_mac_serial.json"
plink.exe -pw securepasswords -ssh root@10.10.10.1 "cp  /root/WebConfigServer/tools/example_cron.txt /persist/crontab"
plink.exe -pw securepasswords -ssh root@10.10.10.1 "cp  /root/WebConfigServer/tools/example_fstab.txt /etc/fstab"
plink.exe -pw securepasswords -ssh root@10.10.10.1 "cp /root/WebConfigServer/tools/WebConfigServer_supervisor.txt /etc/supervisor/conf.d/WebConfigServer.conf"


pscp.exe -pw securepasswords X:\WebConfigServer\*.html root@10.10.10.1:/root/WebConfigServer/
pscp.exe -pw securepasswords X:\WebConfigServer\*.txt root@10.10.10.1:/root/WebConfigServer/
pscp.exe -pw securepasswords X:\WebConfigServer\cronqueue\* root@10.10.10.1:/root/WebConfigServer/cronqueue/
pscp.exe -pw securepasswords X:\WebConfigServer\static\* root@10.10.10.1:/root/WebConfigServer/static/

rem pscp.exe -pw securepasswords X:\WebConfigServer\certs\id_rsa_WebConfigServer.pub root@10.10.10.1:/root/.ssh/id_rsa.pub
pscp.exe -pw securepasswords X:\WebConfigServer\certs\authorized_keys root@10.10.10.1:/root/.ssh/authorized_keys
 
plink.exe -pw securepasswords -ssh root@10.10.10.1 "rm -f /tmp/WebConfigServer*.log"

plink.exe -pw securepasswords -ssh root@10.10.10.1 "pkill -9 -f WebConfigServer"

plink.exe -pw securepasswords -ssh root@10.10.10.1 "mount / -o remount,ro"


rem uncomment this when the box you are deploying to is going to is about to be "cloned" ( ie on last boot before powerdown )
plink.exe -pw securepasswords -ssh root@10.10.10.1 "touch /persist/noidentity.txt"

timeout /T 30
