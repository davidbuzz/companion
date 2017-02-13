cd X:\WebConfigServer\tools

#pscp.exe -pw securepasswords root@192.168.192.30:/root/WebConfigServer/*.py X:\WebConfigServer\ 
#pscp.exe -pw securepasswords root@192.168.192.30:/root/WebConfigServer/*.html X:\WebConfigServer\ 
#pscp.exe -pw securepasswords root@192.168.192.30:/root/WebConfigServer/*.txt X:\WebConfigServer\
pscp.exe -pw securepasswords root@192.168.192.30:/root/WebConfigServer/tools/* X:\WebConfigServer\tools\
#pscp.exe -pw securepasswords root@192.168.192.30:/root/WebConfigServer/cronqueue/* X:\WebConfigServer\cronqueue\
timeout /T 3
