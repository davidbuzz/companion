from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint
import multiprocessing 
import sys
import time
import setproctitle
from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping
from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config,check_crontab_queue 
#make_server_manager,make_client_manager

from SerialReaderWriter import SerialReaderWriter
from SerialPacketHandler import SerialPacketHandler
from tornado_ws_server import WebAndSocketServer
from portal_tornado_ws_server_simulator import PORTALWebAndSocketServer
from ws4py_ws_client import WebAndSocketClient   
from cron_reader_thread import SlowActionsThread 
from SimplePriorityQueue import SimplePriorityQueue

import binascii
from struct import *
import serial

from os import listdir, rename
from os.path import isfile, join
import os
import json
import signal

def namestr(obj, namespace):
    return [name for name in namespace if namespace[name] is obj]

if __name__ == '__main__':


    pid = os.getpid()
    setproctitle.setproctitle("APSync Main")
    print("Starting: MAIN process with PID: %d " % ( pid))

    sys.stdout = CustomPrint(sys.stdout,"MAIN> ","WebConfigServer_main.log")

    # we start here and go up.
    #PORTNUM = 23456

    #import logging
    #logger = multiprocessing.log_to_stderr()
    #logger.setLevel(multiprocessing.SUBDEBUG)



    # serial port handling  ... bytes to packets..
    lowserial_input_queue = SimplePriorityQueue(2) #SimplePriorityQueue(2) #multiprocessing.Queue()   # we send data TO the serial input device
    lowserial_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()  # get from
    # .. and packets to interactions.
    serialpacket_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()   # we send data TO the serial input device
    serialpacket_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()  # get from


    # our webclient
    portalclient_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # we send data TO the portal client device
    portalclient_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get from


    # our local webserver also has queues for the web interface  ( config tools and monitoring ) 

    web_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # we send data TO the local HTTP and websockets process
    web_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get from 


    # our slow-actions thread also has queues for the interface  ( cron, wifi tests, daily actions, etc ) 
    slow_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # we send data TO the 'slow actions' process
    slow_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get from 

    # these queues are NOT for normal JSON comms... its just so we get a regular 'ping' to tell us the PORTAL simulator is still running ok. 
    sim_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     #unused, just here for consistency 
    sim_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get pings only from... 

    # for sharing key data ( the gDEVICES hash from the serialrw module ) 
    manager = multiprocessing.Manager()
    gDEVICES = manager.dict()

    delay = 1.0
    smalldelay = 0.1
    last_check_time = 0

    #print("sleeping 1 for attach of debugger")
    #time.sleep(1)
    #webclient = None
    #webserver = None
    #slowserver = None
    #gw = None
    #portalwebserver = None

    # another way of looking at them...
    processes = {'webclient':None,'webserver':None,'slowserver':None,'lowgw':None,'packetgw':None,'portalwebserver':None}

    tasklist = {}  # the list of pids and how recently we heard from them via a ping.

    # the reason we create the "loop" at this point is so that the above queue's are only created ONCE...
    # but the below processe/s might need to be re-created if the crash or hang... etc 

    while ( True ):   # are we running with a simulated PORTAL server, or an an actual one? 

        config = read_config();
        #portalurl1 = 'wss://'+config['portal1']+'/ws/'
        #portalurl2 = 'wss://'+config['portal2']+'/ws/'
        portalurl1 = config['portal1']
        portalurl2 = config['portal2']
        #portalurl='ws://127.0.0.1:9999/ws/'  # unsecure version is just ws: not wss:

        
        if processes['webclient'] == None:
            # lets try to start the websocket CLIENT  ...
            processes['webclient'] = WebAndSocketClient(portalclient_input_queue, portalclient_output_queue,gDEVICES,portalurl1)
            processes['webclient'].daemon = True
            processes['webclient'].start()
            #time.sleep(delay); # just cause.  

        if processes['webserver'] == None:
            # lets try to start the local tornado webserver ... on port 8888
            processes['webserver'] = WebAndSocketServer(web_input_queue,web_output_queue)
            processes['webserver'].daemon = True
            processes['webserver'].start()
            #time.sleep(delay); # just cause.  

        if processes['slowserver'] == None:
            # lets try to start the background / slow actions / cron thread
            processes['slowserver'] = SlowActionsThread(slow_input_queue,slow_output_queue)
            processes['slowserver'].daemon = True
            processes['slowserver'].start()

        if sys.platform == 'win32':
            serialdevice = 'com33'
        else:
            #serialdevice = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AL01NTI7-if00-port0'
            #serialdevice = '/dev/ttyAMA0'
            serialdevice = '/dev/ttyUSB0'

        #  Low level serial port handler only. 
        if processes['lowgw'] == None:
            # now we try to attach to the serial device, if we can. 
            processes['lowgw'] = SerialReaderWriter( lowserial_input_queue, lowserial_output_queue, gDEVICES , serialdevice )   # the comport is selected in __init__ in the SerialReaderWriter.py file. 
            processes['lowgw'].daemon = True
            processes['lowgw'].start()
            processes['lowgw'].expecting_ack = False
            time.sleep(1); # seems to need at least a second here. - windowsism? 
            #print("expecting ack = False")

        # high level serial packet handler
        if processes['packetgw'] == None:
            # now we try to attach to the serial device, if we can. 
            processes['packetgw'] = SerialPacketHandler( serialpacket_input_queue, serialpacket_output_queue, gDEVICES  )  
            processes['packetgw'].daemon = True
            processes['packetgw'].start()
            processes['packetgw'].expecting_ack = False
            time.sleep(1); # seems to need at least a second here. - windowsism? 
            #print("expecting ack = False")


        if ( True ):   # are we running with a simulated PORTAL server, or an an actual one? 
            if processes['portalwebserver'] == None:
                # try to start the PORTAL simulation server - it's also tornado as that's convenient. it's on port 9999
                processes['portalwebserver'] = PORTALWebAndSocketServer(sim_input_queue,sim_output_queue)
                processes['portalwebserver'].daemon = True
                processes['portalwebserver'].start()
                #time.sleep(delay); # just cause.  
   
        #print "sleeping 10 for threads debug"
        #time.sleep(10)

        queue_check_list = [lowserial_output_queue,serialpacket_output_queue,portalclient_output_queue,web_output_queue,slow_output_queue,sim_output_queue]



        # ALL messages that are "route-ed" should be json_wrap_with_target() on the way *out* from each respective module to arrive here, 
        #   but NOT on data that is on the way IN  ( departing this router) , as the router already decided that.

        # TODO busy/quiet check ( eg if we haven't seen anything in a queue for a second, it's "not busy", so we could check it a bit slower ). 

        now = int(time.time())  # time in exact seconds
        if now > last_check_time+10: # we post idle message at least every 10 secs
            last_check_time = now
            print "main loop is idling"
            # review the pids every 10 secs and see if they called home properly
            for pid in tasklist.keys():   # the .keys() avoids RuntimeError
                if tasklist[pid] != None:
                    recency = (tasklist[pid]['time']+55)  # 10 second check period, plus some extra seconds 'grace'

    #processes = {'webclient':None,'webserver':None,'slowserver':None,'lowgw':None,'packetgw':None,'portalwebserver':None}

                    proc = tasklist[pid]['name']  # the name passed into queue_ping() calls must match the process names used here
                    if now>recency:
                        print "###BAM! STRAIGHT IN THE KISSER! :"+str(pid)
                        print "###BAM! STRAIGHT IN THE KISSER! :"+str(pid)
                        print "###we havent heard from "+proc+" for seconds:"+str(now-recency)
                        print "###BAM! STRAIGHT IN THE KISSER! :"+str(pid)
                        print "###BAM! STRAIGHT IN THE KISSER! :"+str(pid)
                        # first we'll try to terminate it as a valid multiprocess activity...
                        # then....

                        kill_nonresponsive_processes = True  # change this as required. 

                        if kill_nonresponsive_processes:
                            #try:
                            processes[proc].terminate() #AttributeError: 'NoneType' object has no attribute 'terminate'
                            #except:
                            #    pass
                            time.sleep(0.1)
                            #try:
                            os.kill(pid,signal.SIGTERM)  # nice
                            #except:
                            #    pass
                            time.sleep(0.1)
                            #try:
                            os.kill(pid,signal.SIGKILL)  # forceful
                            #except:
                            #    pass
                            #time.sleep(0.1)

                            processes[proc] = None    # clear the variable so we can restart it next loop! 
                            #tasklist[pid] = None   # forget the old pid, so we don't keep trying to kill it
                            tasklist.pop(pid,None)

                        # tell the user / logging subsystem...
                        j = {}
                        j['pid'] = pid
                        j['recency'] = str(now-recency)
                        j['proc'] = proc
                        l = {}
                        l['PROCESS_KILLED'] =  j
                        web_input_queue.put(1,l)


        time.sleep(0.1)        

        # TIPS:
        ## the serial thread passes outgoing data to the PORTAL client primarily, and the web server so that any connected webclient can see the debug stuff
        ## data FROM the portal client ( and thus from the PORTAL server ) goes to the serial and http server locations
        ## data FROM the local HTTP server ( representing the browser and user ) , then this is SIMULATION data, and we know where to route it to ( serial or the portal )
        #

        # just some debug / display printing....
        allzeros = True
        maybe_print = "\n"
        for _thisqueue in queue_check_list:
            x = namestr(_thisqueue, globals()) # pull variable name from introspection of object
            y = list(x) # an explicit copy
            y.sort()    # so we can pick the right one by its position
            maybe_print = maybe_print+"current queue: "+str(y[1])+"            size: "+str(_thisqueue.qsize())+"\n"
            if _thisqueue.qsize() > 0:
                allzeros = False

        if not allzeros:
            print maybe_print
            print "--------------------------------------------------------"
        # end of the debug / print code. 

        for _thisqueue in queue_check_list:
            while not _thisqueue.empty():   # while or if? # first method is 'if'. 
                s = _thisqueue.get_nowait()
                (target,data,priority) = json_unwrap_with_target(s)

                if target != False:
                    print "Routing some packet OUT with destination: "+target
                    #TODO check if the queue we came from is the queue we are going to put it into, and drop it to prevent loops...
                    if ( target == 'logging'):
                        web_input_queue.put(priority,data)
                    if ( target == 'portalclient'):
                        #print "EEPPORTALCLIENT"+repr(data)
                        portalclient_input_queue.put(priority,data)
                    if ( target == 'serialrw'): # low latency bytes->packets
                        #print "EEPSERIAL"+repr(data)
                        lowserial_input_queue.put(priority,data)
                    if ( target == 'serialpacket'):  # slower packets -> interactions
                        #print "EEPPACKET"+repr(data)
                        serialpacket_input_queue.put(priority,data)
                    if ( target == 'slowserver'):
                        slow_input_queue.put(priority,data)
                    if ( target == 'watchtasks'):
                        t = json.loads(data)
                        tasklist[t['pid']] = t # remember the process id and the time etc
                        #print repr(data)

                if  ( target == False):
                    print "1/ERROR FAILED TO ROUTE UNTARGETED DATA:"+data

                s = None
                target = False
                data = False




# future enhancement- proper cleanup of the resources on crash.   it's OK, the undelying OS will do that for us when we are killed off.   :-) 
#    gw.close()
#    web.close()

