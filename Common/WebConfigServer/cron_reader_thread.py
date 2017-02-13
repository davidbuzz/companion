# run then browse to http://127.0.0.1:8888/
# http://en.proft.me/2014/05/16/realtime-web-application-tornado-and-websocket/ 
from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint

import json
import setproctitle

from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping
from file_utils import read_passwd_file, file_get_contents, file_put_contents, read_config, write_config, check_crontab_queue,do_interfaces_file

import sys  # for sys.platform win32 vs linux test
from multiprocessing import Process
import multiprocessing
import time
import os
import subprocess
import re
#import wifitest
from SimplePriorityQueue import SimplePriorityQueue

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


def emit_stage(stage,shortmsg = "Wifi Test In Progress.....", color = "#66ff33" , stat = "OK"):
    global goutq
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
    #m = json.loads(stage_msg)
    #goutq.put(1,json_wrap_with_target(m,'logging'))
    goutq.put(1,stage_msg) # as it's already wrapped in stage_msg

    #resultfile = '/root/WebConfigServer/cronqueue/wifitestresult.json'	
    #file_put_contents(resultfile+".done",stage_msg)
    #os.rename(resultfile+".done", resultfile)





def start_wifi_test():
    #global ginq
    global goutq

    # note that we do something similar, but not identical in wifitest.py ( it's for CRON use, not GUI ) 

    do_interfaces_file()

    emit_stage(1)

    print "please wait up-to 30 seconds for wifi to stabilise......"

    cmd1 = 'ifdown wlan0 2>/dev/null >/dev/null'
    print cmd1
    ret = subprocess.call(cmd1,shell=True,stdout=open('/dev/null', 'w'),stderr=open('/dev/null', 'w'))

    emit_stage(2)
    time.sleep(1)

    cmd1 = 'ifup wlan0 2>/dev/null >/dev/null'
    print cmd1
    ret = subprocess.call(cmd1,shell=True,stdout=open('/dev/null', 'w'),stderr=open('/dev/null', 'w'))

    emit_stage(3)
    time.sleep(1)

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
    ret = ping('google.com')

    # if alive
    stat = ''
    if ret == 0:
        shortmsg = "The test of the wifi connection went OK!"
        stat = "OK"	
        color = "#66ff33"  # green = good. 
    else:
        shortmsg = "Sorry, the Tested WIFI was unable to be used."
        stat = "FAIL"
        color = "#ff6666"   # red = fail.
    
    emit_stage( 5,shortmsg,color,stat)


    # only if we got a ping from google, leave that as our default route for the moment... 
    if ret != 0:
        # I know the eth0 might not even be up, but if it is, we might as well use it if we don't have ping thru wlan0
        # the result of this commmand is that after running this script, the machine will loose its internet route if 
        # its not on eth0
        cmd4 = 'route del default ; route add default gw '+r+' eth0'
        print cmd4
        ret = subprocess.call(cmd4,shell=True,stderr=subprocess.STDOUT)

    
    # present the over-view status of the tests... 
    # in-short, if the PING went ok, the test is OK. 
    # this is the same as stage 5 , but the <div> we target is different, see index.template.html 
    emit_stage(6,shortmsg,color,stat)


    return True


ginq = None
goutq = None

### check the queue for pending messages, and rely that to all connected clients
#def checkQueue():
#    #print("tornado checking queue")
#    global ginq
#    global goutq
#    if not ginq.empty():
#        message = ginq.get()
#        #for c in WebSocketHandler.waiters.:
#        #    c.write_message(message)
#        print("Got a message from the queue to tornado....")
#        WebSocketHandler.send_updates(message)   # sends to all WS clients that are connected.

def cronmain(inq, outq):
    global ginq
    global goutq
    ginq = inq  
    goutq = outq
    lastcronchecktime = 0  # 1 sec counter
    last_check_time = 0    # 10 sec counter
    while True:
        #print "doing background handler..."

        # other regular event/s... we'll do with a crontab that is checked once a second.
        # the filesystem is efectively of the "queue" that we handle for incoming data to here. 

        now = int(time.time()) # time in exact seconds

        # 1 second loop
        if now > lastcronchecktime: # has a second passed? 
            lastcronchecktime = now
            filefound = check_crontab_queue() # look to see if theres anything on-disk for us.
            if filefound != "":
                filedata = file_get_contents(filefound)
                os.rename(filefound,filefound+".done"); # or we'll find the same file again.

                (target,data,priority) = json_unwrap_with_target(filedata)    # future enhancement... write a convenience script to create this file/cron data in the valid format using json_wrap_with_target()
                if ( target == 'slowserver'):
                        # if it' for us to do immediatelly..? 
                        handle_queue_data(data)
                else:
                    # after getting from disk, push to outgoing queue to be 'routed' to its destination.
                    goutq.put(priority,filedata);

        # 10 second loop.
        if now > last_check_time+10: # we post idle message at least every 10 secs
            last_check_time = now
            print "cron_reader loop is idling"
            ## ping central thread to tell them we are still here...
            queue_ping(goutq,'slowserver')

        
        if not ginq.empty():   # data for the local 'slow' server 
            s = ginq.get_nowait()
            print s
            handle_queue_data(s)
            #(target,data,priority) = json_unwrap_with_target(s) 
            #if ( target == 'slowserver'):
            #        print "slowserver is handling incoming queue data"+str(data)
            #        handle_queue_data(data)
            #else:
            #        print "bad routing data sent to slowserver thread, ignored it, sorry."+str(data)


        time.sleep(0.2)  # yep, slow. 


def handle_queue_data(data):
    try:
        json_data = json.loads(data)
    except ValueError:
        print "unable to parse JSON data, sorry"+data
        json_data = data

    print repr(json_data)

    # handle our first possible action..
    if ('WIFITEST' in json_data):
        print "running start_wifi_test()"
        start_wifi_test()

    # todo put other possible actions here: 

    #if 
                #j = {}
                #j['WIFISTATUS']={}
                #j['WIFISTATUS']['color'] = color
                #j['WIFISTATUS']['response'] = msg

   # pass

# if requested to start from multiprocess module, spinup this way in it's own process.
class SlowActionsThread(Process):
        def __init__(self, web_input_queue, web_output_queue):
            self.input_queue = web_input_queue
            self.output_queue = web_output_queue
            Process.__init__(self)
            pass

        def run(self):
            #with modified_stdout("SLOWACTIONS> ", logfile='WebConfigServer_slowactions.log'):
                sys.stdout = CustomPrint(sys.stdout,"SLOWACTIONS> ","WebConfigServer_slowactions.log")
                print("starting SLOWACTIONS handler in own process, thx.")
                proc_name = self.name
                pid = os.getpid()
                setproctitle.setproctitle("APSync Slow")
                print("Starting: %s process with PID: %d " % (proc_name, pid))

                cronmain(self.input_queue,self.output_queue)  # passing input and output queue/s from object into non-object call.
                pass


# if called directly from the cmd line, just start the web server stand-alone.
if __name__ == '__main__':
    print("starting SLOWACTIONS handler standalone... thx.")
    input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # we send data TO the local process
    output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get from 

    testdata = '''{
      "_target": "slowserver",
      "data": {
        "WIFIAVAILABLE": {
          "Yes": "1"
        }
      }
    }'''
    input_queue.put(1,testdata)  # handle it

    badtestdata = '''{
      "_target": "xxx",
      "data": {
        "xxxxtyyyy": {
          "Yes": "1"
        }
      }
    }'''
    input_queue.put(1,badtestdata)  # ignore it. 

    wifitestdata = '''{
      "_target": "slowserver",
      "data": {
        "WIFITEST": 1
      }
    }'''
    input_queue.put(1,wifitestdata)  # trigger event as a result of it. 
    
    cronmain(input_queue,output_queue)

