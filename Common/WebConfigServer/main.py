from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint
import multiprocessing 
import sys
import time
import setproctitle
from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping
from file_utils import read_passwd_file, file_get_contents, file_put_contents,read_config,check_crontab_queue 

# uncomment more of these to enable some optional features - will need help to make them work 
#from SerialReaderWriter import SerialReaderWriter
#from SerialPacketHandler import SerialPacketHandler
from tornado_ws_server import WebAndSocketServer
#from portal_tornado_ws_server_simulator import PORTALWebAndSocketServer
#from ws4py_ws_client import WebAndSocketClient   
#from cron_reader_thread import SlowActionsThread 
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

    # create a bunch of named queues for each of the potential sub-processes we'll monitor.
    # in and out are a pair, we use pretty much everywhere.
    def queue_pair(x):
        return SimplePriorityQueue(x), SimplePriorityQueue(x)
    # 'input' -> we send data TO the serial input device, and  'output' -> we get from it 
    lowserial_input_queue, lowserial_output_queue = queue_pair(2) # out serial byte handler ( fast serial no blocking ) 
    serialpacket_input_queue, serialpacket_output_queue = queue_pair(2)  # out serial packet handler ( slow, higher level )
    portalclient_input_queue, portalclient_output_queue = queue_pair(2) # our webclient
    web_input_queue, web_output_queue  = queue_pair(2)  # our local webserver also has queues for the web and websockets  ( config tools and monitoring ) 
    slow_input_queue, slow_output_queue = queue_pair(2) # can be things line cron, wifi tests, slow activities
    sim_input_queue, sim_output_queue = queue_pair(2)   #  PORTAL or other simulator, not normally used for JSON, just heartbeats.

    # this is an example of how we can have a python dict that's available to *all* processes, if we want.   eg a list of connected clients or something.
    # not really used right now though. 
    manager = multiprocessing.Manager()
    gDEVICES = manager.dict()

    delay = 1.0
    smalldelay = 0.1
    last_check_time = 0

    # another way of looking at them...
    processes = {'webclient':None,'webserver':None,'slowserver':None,'lowgw':None,'packetgw':None,'portalwebserver':None}

    tasklist = {}  # the list of pids and how recently we heard from them via a ping.

    # the reason we create the "loop" at this point is so that the above queue's are only created ONCE...
    # but the below processe/s might need to be re-created if the crash or hang... etc 

    while ( True ):   # are we running with a simulated PORTAL server, or an an actual one? 

        config = read_config();
        # this allows us to re-read the 'portal' values from the config, if they exist, and pass updated versions of them to the procese/s that needs it.
        try: 
            portalurl1 = config['portal1']
            portalurl2 = config['portal2']
        except KeyError as e:   # right now we don't really care if 'portal1' or 'portal2' is in the data rom the client, so let it slide if it's not.
            portalurl1 = ''
            portalurl2 = ''
            pass

        # (re)start the process if it's not already running        
        if processes['webclient'] == None:
            try: 
                # lets try to start the websocket CLIENT  ...
                processes['webclient'] = WebAndSocketClient(portalclient_input_queue, portalclient_output_queue,gDEVICES,portalurl1)
                processes['webclient'].daemon = True
                processes['webclient'].start()
                #time.sleep(delay); # just cause.  
            except NameError:
                print "WebAndSocketClient feature currently disabled, sorry.";
                processes['webclient'] = -1;


        if processes['webserver'] == None:
            # lets try to start the local tornado webserver ... on port 8888
            processes['webserver'] = WebAndSocketServer(web_input_queue,web_output_queue)
            processes['webserver'].daemon = True
            processes['webserver'].start()
            #time.sleep(delay); # just cause.  

        if processes['slowserver'] == None:
            try: 
                # lets try to start the background / slow actions / cron thread
                processes['slowserver'] = SlowActionsThread(slow_input_queue,slow_output_queue)
                processes['slowserver'].daemon = True
                processes['slowserver'].start()
            except NameError:
                print "SlowActionsThread feature currently disabled, sorry.";
                processes['slowserver'] = -1;


        if sys.platform == 'win32':
            serialdevice = 'com33'
        else:
            #serialdevice = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AL01NTI7-if00-port0'
            #serialdevice = '/dev/ttyAMA0'
            serialdevice = '/dev/ttyUSB0'

        #  Low level serial port handler only. 
        if processes['lowgw'] == None:
            try: 
                # now we try to attach to the serial device, if we can. 
                processes['lowgw'] = SerialReaderWriter( lowserial_input_queue, lowserial_output_queue, gDEVICES , serialdevice )   # the comport is selected in __init__ in the SerialReaderWriter.py file. 
                processes['lowgw'].daemon = True
                processes['lowgw'].start()
                processes['lowgw'].expecting_ack = False
                time.sleep(1); # seems to need at least a second here. - windowsism? 
                #print("expecting ack = False")
            except NameError:
                print "SerialReaderWriter ( low level serial) feature currently disabled, sorry.";
                processes['lowgw'] = -1;

        # high level serial packet handler
        if processes['packetgw'] == None:
            try: 
                # now we try to attach to the serial device, if we can. 
                processes['packetgw'] = SerialPacketHandler( serialpacket_input_queue, serialpacket_output_queue, gDEVICES  )  
                processes['packetgw'].daemon = True
                processes['packetgw'].start()
                processes['packetgw'].expecting_ack = False
                time.sleep(1); # seems to need at least a second here. - windowsism? 
                #print("expecting ack = False")
            except NameError:
                print "SerialPacketHandler( high level serial) feature currently disabled, sorry.";
                processes['packetgw'] = -1;


        # are we running with a simulated PORTAL server, or an an actual one? 
        if processes['portalwebserver'] == None:
            try: 
                # try to start the PORTAL simulation server - it's also tornado as that's convenient. it's on port 9999
                processes['portalwebserver'] = PORTALWebAndSocketServer(sim_input_queue,sim_output_queue)
                processes['portalwebserver'].daemon = True
                processes['portalwebserver'].start()
                #time.sleep(delay); # just cause.  
            except NameError:
                print "PORTALWebAndSocketServer feature currently disabled, sorry.";
                processes['portalwebserver'] = -1;

        #print "sleeping 10 for threads debug"
        #time.sleep(10)

        # check all the lists if all features are disabled...? 
        #queue_check_list = [lowserial_output_queue,serialpacket_output_queue,portalclient_output_queue,web_output_queue,slow_output_queue,sim_output_queue]

        # absolute minimal list of queues to check: 
        queue_check_list = [ web_output_queue ]



        # ALL messages that are "route-ed" should be json_wrap_with_target() on the way *out* from each respective module to arrive here, 
        #   but NOT on data that is on the way IN  ( departing this router) , as the router already decided that.

        # TODO busy/quiet check ( eg if we haven't seen anything in a queue for a second, it's "not busy", so we could check it a bit slower ). 

    #    # this IF block works on the idea that every subprocess we spinup constantly sends us at the very least a "heartbeat" type packet every 10 seconds or so
    #    # and this loop's job is to kill-off processes that haven't sent a heartbeat recently. ( and they'll be respawned ) 
    #    now = int(time.time())  # time in exact seconds
    #    if now > last_check_time+10: # we post idle message at least every 10 secs
    #        last_check_time = now
    #        print "main loop is idling"

    #        # review the pids every 10 secs and see if they called home properly
    #        for pid in tasklist.keys():   # the .keys() avoids RuntimeError
    #            if tasklist[pid] != None:
    #                recency = (tasklist[pid]['time']+55)  # 10 second check period, plus some extra seconds 'grace'

    ##processes = {'webclient':None,'webserver':None,'slowserver':None,'lowgw':None,'packetgw':None,'portalwebserver':None}

    #                proc = tasklist[pid]['name']  # the name passed into queue_ping() calls must match the process names used here
    #                if now>recency:
    #                    print "###we havent heard from "+proc+" for seconds:"+str(now-recency)
    #                    print "###BAM! STRAIGHT IN THE KISSER! :"+str(pid)
    #                    # first we'll try to terminate it as a valid multiprocess activity...
    #                    # then....

    #                    kill_nonresponsive_processes = True  # change this as required. 

    #                    if kill_nonresponsive_processes:
    #                        #try:
    #                        processes[proc].terminate() #AttributeError: 'NoneType' object has no attribute 'terminate'
    #                        #except:
    #                        #    pass
    #                        time.sleep(0.1)
    #                        #try:
    #                        os.kill(pid,signal.SIGTERM)  # nice
    #                        #except:
    #                        #    pass
    #                        time.sleep(0.1)
    #                        #try:
    #                        os.kill(pid,signal.SIGKILL)  # forceful
    #                        #except:
    #                        #    pass
    #                        #time.sleep(0.1)

    #                        processes[proc] = None    # clear the variable so we can restart it next loop! 
    #                        #tasklist[pid] = None   # forget the old pid, so we don't keep trying to kill it
    #                        tasklist.pop(pid,None)

    #                    # tell the user / logging subsystem...
    #                    j = {}
    #                    j['pid'] = pid
    #                    j['recency'] = str(now-recency)
    #                    j['proc'] = proc
    #                    l = {}
    #                    l['PROCESS_KILLED'] =  j
    #                    web_input_queue.put(1,l)


        time.sleep(0.1)        



        # just some debug / display printing....
        allzeros = True # False to verbose output when queues are empty. 
        maybe_print = "\n"
        for _thisqueue in queue_check_list:
            x = namestr(_thisqueue, globals()) # pull variable name from introspection of object
            y = list(x) # an explicit copy
            y.sort()    # so we can pick the right one by its position
            maybe_print = maybe_print+"current queue: "+str(y[1]) #+"            size: "+str(_thisqueue.qsize())+"\n"
            if _thisqueue.empty() != False:
                allzeros = False

        if not allzeros:
            print maybe_print
            print "--------------------------------------------------------"
        # end of the debug / print code. 


        # check all queues for outgoing packets, peek inside them to see where they are going ( "target" ), then sent them to the target.
        for _thisqueue in queue_check_list:
            while not _thisqueue.empty():   # while or if? # first method is 'if'. 
                s = _thisqueue.get_nowait()
                (target,data,priority) = json_unwrap_with_target(s)
                #print "(target,data,priority) : %s %s %s )" % (target,data,priority)
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
                    if ( target == 'watchtasks'): # all tasks that might crash send us these in a consistent format, so we just action them here: 
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

