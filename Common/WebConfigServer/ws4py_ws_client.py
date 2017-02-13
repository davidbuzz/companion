# BUZZ: this WS client works well. 
# https://ws4py.readthedocs.io/en/latest/sources/clienttutorial/
# http://www.tornadoweb.org/en/stable/ioloop.html
# http://stackoverflow.com/questions/12479054/how-to-run-functions-outside-websocket-loop-in-python-tornado


from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint

from ws4py.client.tornadoclient import TornadoWebSocketClient
from ws4py.messaging import TextMessage   # so we can fake one when simulating messages from the PORTAL :-) 
#from tornado import ioloop
import tornado.ioloop
import multiprocessing
import time 
import json
import setproctitle

from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping,log_to_file
from file_utils import read_passwd_file, file_get_contents, file_put_contents, read_config,read_my_mac_address,change_leds

import os
import sys
import base64
from SimplePriorityQueue import SimplePriorityQueue


last10_check_time = 0
last30_check_time = 0

glast_seen_response = int(time.time())


class MyWSClient(TornadoWebSocketClient):
     def __init__(self,ws, inq=None, outq=None,  gDEVICES=None, protocols=['http-only', 'chat'], extensions=None, io_loop=None, ssl_options=None, headers=[]):

         try:
            super( MyWSClient, self ).__init__(ws, protocols=protocols, extensions=extensions,io_loop=io_loop,ssl_options=ssl_options, headers=headers)
         except: 
            print "OOPS, EXCEPTION MAKING WS CLIENT"
            print "OOPS, EXCEPTION MAKING WS CLIENT"
            print "OOPS, EXCEPTION MAKING WS CLIENT"

         self.inq = inq
         self.outq = outq
         #self._opened = False
         self.gDEVICES = gDEVICES
         self.myMAC = read_my_mac_address()
         glast_seen_response = int(time.time())  # time in exact seconds
         self.new = True   # just created! , have we even been "opened " yet? 
         change_leds(None,None,0)  # blue disable, if not already
         self.last_msg_sent = 0   # 
         self.config = read_config()


#   def on_connection_close(self):
#        pass

     def opened(self):
         #self._opened = True
         self.new = False
         print "WS client connection opened!"
         # tell the other end our MAC address ( of the gateway ) 
         self.send('{ "Hello": "'+self.myMAC+'" }')
         glast_seen_response = int(time.time())  # time in exact seconds

         # tell serial packet module to generate a DeviceUpdateRequest back to PORTAL..... ( yes, I know we could just talk to the portal direct from here ).
         #if self.config['devupconnect'] == "True":
         self.outq.put(1,json_wrap_with_target(json.loads('{ "DeviceUpdateRequest": [ "ff:ff:ff:ff:ff:ff" ] } '),'serialpacket'))  


     def closed(self, code, reason=None):
         print "WS client connection closed...? "
         #self._opened = False
         change_leds(None,None,0)  # blue disable, if not already
         if self.new == False:
            print "closed() was called on websocket after it was open! "            
            tornado.ioloop.IOLoop.instance().stop()

     def received_message(self, m):
         change_leds(None,None,1)  # blue enable, if not already
         global glast_seen_response
         #self._opened = True # in-case it wasn't, just to be sure. 
         print "WS message recived!"
         print m.data
         j = None
         # try to handle non-json data just enough to warn about it and pass it anyway....
         #try:
         j = json.loads(m.data)
         #except ValueError:
         #   print "unable to parse JSON data, sorry"+m.data
         #   j = m.data

         #  browser / logger, we assume everything coming in this function is "FROMPORTAL", it's pretty safe, most of the time.
         l = {}
         l['FROMPORTAL'] =  j
         self.outq.put(1,json_wrap_with_target(l,'logging'))

         json_data = j # compat only..

         # lets also stuff it into a file for later review:
         #log_to_file(".client.IN.json",m.data)

         # {"status":"ok"}
         if ('status' in json_data):
            if (json_data['status'] == 'ok' ) or (json_data['status'] == 'OK') : 
                print "saw a status-ok, or ping response at:"+str(int(time.time()))
                glast_seen_response = int(time.time())  # time in exact seconds
                #print "also with glast_seen_response:"+str(glast_seen_response)
                # we'll then handle the timeout elsewhere. 

         # if server sends us "response" data then its incorrectly echoing back what we are actually supposed to send it, so we'll ignore it.
         if 'response' in json_data :
            if json_data['response'] == 'portal_server_open':
                pass # it's already logged to the browser for the user to see the PORTAL connection is really open... in ws_recv() above
            else:
                print "WHOOPS - not generally response string in data FROM the PORTAL server apart from at startup"
            return


        # Below we handle specific requests that the server might send us... ( right now we  log ( above) then drop them if they aren't one of the below )

         if ('AcknowledgedDeviceStatus' in json_data):

            # Push the request to the router unaltered, for the SERIAL interface to handle further... as this sends a AckDevState as a result
            self.outq.put(1,json_wrap_with_target(json_data,'serialpacket'))   


        # so PORTAL can request a DeviceUpdateRequest, don't normally happen atm, but well allow it. 
         if ('DeviceUpdateRequest' in json_data):
            # Push the request to the router unaltered, for the SERIAL interface to handle further... as this sends a DeviceUpdate as a result
            self.outq.put(1,json_wrap_with_target(json_data,'serialpacket'))   


         if ('HighAlert' in json_data) or ('Heartbeat' in json_data):   #these two are equivalent. 
            print("queueing the HighAlert/Heartbeat to outq" )

            devices = self.gDEVICES.copy()  # a safe shallow copy of concurrent dictproxy into local dict

            # assemble a response. ( start empty)
            respond = ''
            if  'HighAlert' in json_data:  #these two are equivalent. 

                # extra feature.... if the mac address we recieve is precisely "ff:ff:ff:ff:ff:ff" then that means "send this to everyone you know"
                sendtoall = False
                for mac in json_data['HighAlert']:
                    if mac == "ff:ff:ff:ff:ff:ff":
                        sendtoall = True
                        print "sendtoall = True"
                if sendtoall == True:
                    for mac in devices:
                        json_data['HighAlert'].append(mac)
                        #print "approved MAC for inclusion- "+mac

                respond =  json.loads('''{ "HighAlert":[ ] }''')
                # we resolve the JSON into a SUBSET of the request , by MAC
                # add those MACs we know about...
                for mac in json_data['HighAlert']:
                     #print "inspecing MAC for inclusion"+mac
                     if mac in devices:
                        respond['HighAlert'].append(mac)
                        #print "approved MAC for inclusion- "+mac
                     else:
                        #print "denied MAC for inclusion- "+mac
                        pass

            if  'Heartbeat' in json_data:  #these two are equivalent.

                # extra feature.... if the mac address we recieve is precisely "ff:ff:ff:ff:ff:ff" then that means "send this to everyone you know"
                sendtoall = False
                for mac in json_data['Heartbeat']:
                    if mac == "ff:ff:ff:ff:ff:ff":
                        sendtoall = True
                        print "sendtoall = True"
                if sendtoall == True:
                    for mac in devices:
                        json_data['Heartbeat'].append(mac)
                        #print "approved MAC for inclusion- "+mac

                respond =  json.loads('''{ "Heartbeat":[ ] }''')
                # we resolve the JSON into a SUBSET of the request , by MAC
                # add those MACs we know about...
                for mac in json_data['Heartbeat']:
                     #print "inspecting MAC for inclusion"+mac
                     if mac in devices:
                        respond['Heartbeat'].append(mac)
                        #print "approved MAC for inclusion- "+mac
                     else:
                        #print "denied MAC for inclusion- "+mac
                        pass

            # Push the request to the router unaltered, for the SERIAL interface to handle further...
            self.outq.put(0,json_wrap_with_target(json_data,'serialpacket'))

            # add something to keep it different.
            respond['response'] = 'Xthanks'

            # finally, respond to the WS request from PORTAL
            result = json.dumps(respond,indent=2,sort_keys=True)
            self.send(result)

         if ('AllClear' in json_data):
            print("queueing the AllClear to outq" )

            devices = self.gDEVICES.copy()  # a safe shallow copy of concurrent dictproxy into local dict

            # extra feature.... if the mac address we recieve is precisely "ff:ff:ff:ff:ff:ff" then that means "send this to everyone you know"
            sendtoall = False
            for mac in json_data['AllClear']:
                if mac == "ff:ff:ff:ff:ff:ff":
                    sendtoall = True
            if sendtoall == True:
                for mac in devices:
                    json_data['AllClear'].append(mac)
                    #print "approved MAC for inclusion"+mac

            # Push the request to the router unaltered, for the SERIAL interface to handle further...
            self.outq.put(0,json_wrap_with_target(json_data,'serialpacket'))

            # assemble a response. ( start empty)
            respond =  json.loads('''{ "AllClear":[ ] }''')
            # add something to keep it different.
            respond['response'] = 'Ythanks'

            # we resolve the JSON into a SUBSET of the request , by MAC
            # add those MACs we know about...
            for mac in json_data['AllClear']:
                 #print "inspecting MAC for inclusion- "+mac
                 if mac in devices:
                    respond['AllClear'].append(mac)
                    #print "approved MAC for inclusion- "+mac
                 else:
                    #print "denied MAC for inclusion- "+mac
                    pass

            # finally, respond to the WS request from PORTAL
            result = json.dumps(respond,indent=2,sort_keys=True)
            self.send(result)


        # a NetworkReset request does NOT need any specific individual MACs to be reset, it is guaranteed to affect all of them....
        # but we'll respond to the portal server with all teh MACs we know about anyway...
         if ('NetworkReset' in json_data):
            print("queueing the NetworkReset to outq" )

            devices = self.gDEVICES.copy()  # a safe shallow copy of concurrent dictproxy into local dict

            # extra feature.... if the mac address we recieve is precisely "ff:ff:ff:ff:ff:ff" then that means "send this to everyone you know"
            sendtoall = True
            #for mac in json_data['NetworkReset']:
            #    if mac == "ff:ff:ff:ff:ff:ff":
            #        sendtoall = True
            if sendtoall == True:
                for mac in devices:
                    json_data['NetworkReset'].append(mac)
                    #print "approved MAC for inclusion"+mac

            # Push the request to the router unaltered, for the SERIAL interface to handle further...
            self.outq.put(0,json_wrap_with_target(json_data,'serialpacket'))

            # assemble a response. ( start empty)
            respond =  json.loads('''{ "NetworkReset":[ ] }''')
            # add something to keep it different.
            respond['response'] = 'Wthanks'

            # we resolve the JSON into a SUBSET of the request , by MAC
            # add those MACs we know about...
            for mac in json_data['NetworkReset']:
                 #print "inspecting MAC for inclusion- "+mac
                 if mac in devices:
                    respond['NetworkReset'].append(mac)
                    #print "approved MAC for inclusion- "+mac
                 else:
                    #print "denied MAC for inclusion- "+mac
                    pass

            # finally, respond to the WS request from PORTAL
            result = json.dumps(respond,indent=2,sort_keys=True)
            self.send(result)


         if ('ChangeStatus' in json_data):

            devices = self.gDEVICES.copy()  # a safe shallow copy of concurrent dictproxy into local dict

            # extra feature.... if the mac address we recieve is precisely "ff:ff:ff:ff:ff:ff" then that means "send this to everyone you know"
            sendtoall = False
            for mac in json_data['ChangeStatus']:
                if mac == "ff:ff:ff:ff:ff:ff":
                    sendtoall = True
            if sendtoall == True:
                for mac in devices:
                    json_data['ChangeStatus'][mac] = json_data['ChangeStatus']["ff:ff:ff:ff:ff:ff"]
                    #print "approved MAC for inclusion"+mac

            # send it to the serial interface, where they will asyncronously handle it.
            #   note, we send back a response to PORTAL from there, not here. 
            print("queueing the ChangeStatus to outq" )
            self.outq.put(1,json_wrap_with_target(json_data,'serialpacket'))

            # assemble a response. ( start empty)
            respond =  json.loads('''{ "ChangeStatus":{} }''')  # NOT [ and ] like the above two! 
            # add something to keep it different.
            respond['response'] = 'Zthanks'

            # we resolve the JSON into a SUBSET of the request , by MAC
            # add those MACs we know about...
            for mac in json_data['ChangeStatus']:
                 #print "inspecting MAC for inclusion"+mac
                 if mac in devices:
                    #respond['ChangeStatus'] = {}
                    respond['ChangeStatus'][mac] = json_data['ChangeStatus'][mac]   # bring over the number, typically 2 or 4 
                    #print "approved MAC for inclusion"+mac
                 else:
                    #print "denied MAC for inclusion"+mac
                    pass

            # finally, respond to the WS request from PORTAL
            result = json.dumps(respond,indent=2,sort_keys=True)
            self.send(result)



     def checkQueue(self):
        global last30_check_time
        global last10_check_time
        global glast_seen_response

        # don't dequeue next msg till we have waited a few milliseconds from the last one..
        now_ms = int(time.time()*1000)
        if now_ms - self.last_msg_sent < self.config['portalmsgms']:
            return


        # don't de-queue things unless we are connected to the server first.
        #if (self._opened == True ) 
        if (not self.inq.empty() ):
            rawdata = self.inq.get()  # get it as a string
            print "WS picking data from client queue for PORTAL.." #+rawdata
            qdata = json.loads(rawdata);  # convert to python object, assuming its actually json, which it is.

            #sometimes json contains:  'src' = 'portalsimulclient', look for it. 
            src = ''
            if 'src' in qdata:
                src = qdata['src']

            # handle simulated data that could normally come from the websocket (WS) or the normal queue, but when simulated comes from the inq
            if ( src == 'portalsimulclient' ) or ( src == 'portalsimulserver' ) :
                print "handling portalsimul client or server"
                #try:
                #tmp_json_data = qdata['data']   # it's already a python object, just get the relevant bit..
                #print("tmp_json_data: "+repr(tmp_json_data))

                if (  src == 'portalsimulclient' ):
                        print "handling portalsimulclient"
                        data = qdata['data']  #  we're simulating the client, so send it to the real PORTAL server now ( below) ...
                        self.send(json.dumps(data))   # send it as a JSON string, not a python object.
                        return
                if ( src == 'portalsimulserver'):
                        print "handling portalsimulserver"
                        jtext = json.dumps(qdata['data'])  # in the message it's a JSON string, not python.
                        m = TextMessage(jtext)  # ws4py.messaging.TextMessage 
                        # we want this to appear as if it was recieved in def received_message() 
                        self.received_message(m);
               # except BaseException as e:
               #     print "JSON simulator parsing failed, sorry"+str(e)
               #     return

            else:   # normal non-simulated data...     like DeviceChange ( typically 1 device, immediate)  and DeviceUpdate   ( a list of them nightly)    
                #print "normal data"
                self.send(json.dumps(qdata,indent=2,sort_keys=True))
                # note: we handle async reply message/s coming back to us elsewhere, not here 
          
        else:
            pass
            #print "WS NOT OPEN, NOT picking data from queue yet, or the queue is empty"
         
        # 10 second loop.
        now = int(time.time())  # time in exact seconds
        if now > last10_check_time+10: # we post idle message at least every 10 secs
            last10_check_time = now
            print "ws-client loop is idling"  
            ## ping central thread to tell them we are still here...
            queue_ping(self.outq,'webclient')

        # 30 second loop.
        now = int(time.time())  # time in exact seconds
        if now > last30_check_time+60: # we post "Ping" message at least every 60 secs
            last30_check_time = now 
            # ping remote PORTAL to tell them we are still here...
            self.send('{ "Ping": "'+self.myMAC+'" }')
            # we'll check for the ongoing response to this elsewhere, and if we don't keep getting that packet we 
            # freakout and drop the connection and start over. 

        # we send a ping every 60 secs, and if we go more than ~60ish without seeing one, give up on the connection. 
        #if (self._opened == True ) and
        if  (now - glast_seen_response > 65) :
            print "WSCLIENT ABORTING DUE TO NOT SEEING A PING FOR 65 SECS:"+str(glast_seen_response) + " :" + str(now)
            #self._opened = False
            change_leds(None,None,0)  # blue disable, if not already
            glast_seen_response = int(time.time())  
            tornado.ioloop.IOLoop.instance().stop()

     # make the 'send' more verbose etc 
     def send(self,data):
        #if self._opened == True:
            #print "WS sending data to the WS:"+data
            try:
                super( MyWSClient, self ).send(data)  #  RuntimeError("Cannot send on a terminated websocket")
            except RuntimeError as e:
                print "RuntimeError"+str(e)
            except BaseException as e:
                print "BaseException"+str(e)
                #if str(e) == "Stream is closed":
                #    pass
    
            j = None
            # try to handle non-json data just enough to warn about it and pass it anyway....
            try:
                j = json.loads(data)
            except ValueError:
                print "unable to parse JSON data, sorry:"+data
                j = data

            #  browser / logger - this is just to tell the operator/install that the send (above) was successful.
            l = {}
            l['TOPORTAL'] =  j
            self.outq.put(1,json_wrap_with_target(l,'logging'))

            # so we can delay by a configured small amount after each websocket send, to not overwhelm the PORTAL server.... remember the last time we sent one...
            self.last_msg_sent = int(time.time()*1000)



            # lets also stuff it into a file for later review:
            #log_to_file(".client.OUT.json",data)

        #else:
        #    print "WS NOT sending data to the WS, as its closed, sorry."+str(data)
        #    # super hack, this tries to send it anyway. 
        #    # irrespective of self._opened state, and it actually works.
        #    super( MyWSClient, self ).send(data)



# if requested to start from multiprocess module, spinup this way in it's own process.
class WebAndSocketClient(multiprocessing.Process):
        def __init__(self,portalclient_input_queue, portalclient_output_queue,gDEVICES,url='wss://127.0.0.1:9999/ws/'):
            multiprocessing.Process.__init__(self)
            self.input_queue = portalclient_input_queue
            self.output_queue = portalclient_output_queue
            self.gDEVICES = gDEVICES
            self._url = url
            self.ws = None
            pass

        # tell teh websocket to check it's queue , allowing for the fact the websocket might not exist yet.
        def checkQueue(self):
            if self.ws != None:
                self.ws.checkQueue()

        def run(self):
                global glast_seen_response
            #with modified_stdout("PORTALCLIENT> ", logfile='WebConfigServer_portalclient.log'):
                sys.stdout = CustomPrint(sys.stdout,"PORTALCLIENT> ","WebConfigServer_portalclient.log")
                print("starting websocket client in own process, thx.")
                setproctitle.setproctitle("APSync PORTALClient")
                proc_name = self.name
                pid = os.getpid()
                print("Starting: %s process with PID: %d " % (proc_name, pid))

                # for http basic auth: 
                authheader = make_authorization_header()

                # prepare the mainloop
                mainLoop = tornado.ioloop.IOLoop.instance()

                # add scheduler to mainloop before starting it.
                scheduler_interval = 10 #ms? 
                scheduler = tornado.ioloop.PeriodicCallback(self.checkQueue, scheduler_interval, io_loop = mainLoop)
                scheduler.start()

                # need this while True, becuase we've set the MyWSClient object to stop() the entire tornado mainLoop() when it occurs, so we drop out of the mainLoop.start() and come back here on a WS being closed.
                backoff = 1
                which_portal = 1    # 1 or 2 , it's simple
                while True:

                    # check if the _url we are connecting to has been changed... 
                    print "rereading config now...."
                    config = read_config()
                    #portalurl1 = 'wss://'+config['portal1']+'/ws/'
                    #portalurl2 = 'wss://'+config['portal2']+'/ws/'
                    portalurl1 = config['portal1']
                    portalurl2 = config['portal2']

                    if which_portal == 1:
                        # check if the config file was saves, and we need to reload it.
                        if portalurl1 != self._url:
                            print "FOUND NEW PORTAL1 URL! NOW USING: "+str(config['portal1'])
                            self._url = portalurl1;
                        # check if we hit 2x the timeout and will switch to PORTAL2
                        if backoff > int(config['failtime'])*2:
                            print "TIMEOUT. NOW USING PORTAL2: "+str(config['portal2'])
                            self._url = portalurl2;
                            which_portal = 2
                            backoff = 0   # whenever we switch between PORTAL servers, we reset the backoff, and when it exceeds the failtime we try the other.

                    if which_portal == 2:
                        if portalurl2 != self._url:
                            print "FOUND NEW PORTAL2 URL! NOW USING: "+str(config['portal2'])
                            self._url = portalurl2;
                        # check if we hit 2x the timeout and will switch to PORTAL1
                        if backoff > int(config['failtime'])*2:
                            print "TIMEOUT. NOW USING PORTAL1: "+str(config['portal1'])
                            self._url = portalurl1;
                            which_portal = 1
                            backoff = 0   # whenever we switch between PORTAL servers, we reset the backoff, and when it exceeds the failtime we try the other.

                    # give the new ws below ~60secs before we consider it needs to have given us a ping:
                    glast_seen_response = int(time.time())  # now() in exact seconds
   
                    self.ws = MyWSClient(self._url, self.input_queue, self.output_queue, self.gDEVICES, protocols=['http-only', 'chat'] , headers=[('Authorization', authheader ),])

                    print "WS.connect()"
                    self.ws.connect()
                    print "WS.connect() completed ok."

                    change_leds(None,None,0)  # blue disable, if not already

                    # if we have a valid connection, reset the backoff counter...
                    if self.ws.connection != None:
                        backoff = 1
                

                    # start it all - blocks here!
                    print "mainLoop.start()"
                    mainLoop.start()
                    print "mainLoop.start() completed ok"

                    #mainLoop.stop() # don't know if this is relevant. 
    
                    print("---------------------- WARNING mainLoop WARNING ----------------------");
                    print("--------- this is the PORTAL CLIENT restarting unexpectably.  -----------");
                    print("---------------------- WARNING mainLoop WARNING ----------------------");

                    # just to be sure we've fully cloase the WS 
                    print "attempting close"
                    try:
                        self.ws.close_connection()
                        self.ws.close()
                        #self.ws.closed(99)    DONT USE THIS! IT CALLS  tornado.ioloop.IOLoop.instance().stop()
                    except BaseException as e:
                        print "close error"+str(e)
                        #if str(e) == "Stream is closed":
                        #    pass
               
                    # after disconnect and close attempt, drop the ws object.
                    self.ws = None
                    

                    # after the WS is dropped, we'll sleep before retrying
                    print "waiting %d secs before reconnect attempt" % (backoff) 
                    time.sleep(backoff);
                    backoff = backoff*2
                    # max delay before retry is 2 mins
                    if backoff > 120:
                        backoff = 120


def make_authorization_header():
        passwords = read_passwd_file()
        # iterate over the single key thats in there: 
        for meh in passwords:
            username = meh
            password = passwords[username]
        
        # caution, getting this wrong means the server throws a 401 error
        # and getting it right can throw a 200 "error" on misconfigured server/s.
        base64string = base64.encodestring('%s:%s' % (username, password))[:-1]
        authheader =  "Basic %s" % base64string
        return authheader

# if called directly from the cmd line, just start the web client as a stand-alone for testing and easier debugging.
if __name__ == '__main__':
    #with modified_stdout("PORTALCLIENT> "):
        sys.stdout = CustomPrint(sys.stdout,"PORTALCLIENT> ","WebConfigServer_portalclient.log")

        print("starting websocket client standalone... thx.")

       # create incoming queue for things
        inqueue = SimplePriorityQueue(2) #multiprocessing.Queue()  # from multiprocessing     # we can send data TO the portal input device
        outqueue = SimplePriorityQueue(2) #multiprocessing.Queue()  # from multiprocessing     # we can send data TO the portal input device

        gDEVICES = {} # normally this would be shared in real use, but an empty dict works for testing.

        # for http basic auth: 
        authheader = make_authorization_header()

        backoff = 1
        while True:
            # headers must be a tuple in a list, and the trailing comma in the list ensure it's not treated as a single element.
            ws = MyWSClient('wss://127.0.0.1:9999/ws/',  inqueue, outqueue, gDEVICES, protocols=['http-only', 'chat'] , headers=[('Authorization', authheader ),] )

            #inqueue.put(1,"something random"); # borks the thing as its not valid JSON test the queue
            inqueue.put(1,'{"a":"maaate"}'); # test the queue
            inqueue.put(1,'{"b":"52"}'); # test the queue
            inqueue.put(1,'{"c":"3po"}'); # test the queue
            inqueue.put(1,'{"r":{"2":"d2"}}'); # test the queue


            a_bigger_test = '''{
                          "DeviceUpdate": {
                            "aa:bb:cc:dd:ee:ff": {
                              "BatteryLevel": 3.6,
                              "Temperature": 30,
                              "RSSI": 1,
                              "FirmwareVersion": "3.2.4",
                              "NewDeviceStatus": "0",
                              "LastDeviceSeenDateTime": 1465791665,
                              "text1": "",
                              "text2": ""
                            },
                            "aa:bb:cc:dd:ee:ee": {
                              "BatteryLevel": 3.1,
                              "Temperature": 20,
                              "RSSI": 0.9,
                              "FirmwareVersion": "3.2.1",
                              "NewDeviceStatus": "1",
                              "LastDeviceSeenDateTime": 1465791664,
                              "text1": "",
                              "text2": ""
                            },
                            "dd:ee:aa:dd:bb:ee": {
                              "BatteryLevel": 3.1,
                              "Temperature": 20,
                              "RSSI": 0.9,
                              "FirmwareVersion": "3.2.1",
                              "NewDeviceStatus": "1",
                              "LastDeviceSeenDateTime": 1465791664,
                              "text1": "",
                              "text2": ""
                            }
                          }
                        }'''
            inqueue.put(1,a_bigger_test);

            another_big_test = '''
                        {
                            "DeviceChange": {
                                "eb:4f:80:b6:6a:e7": {
                                "BatteryLevel": "f4 0f", 
                                "FirmwareVersion": "0.9.9", 
                                "LastDeviceSeenDateTime": 1466403342, 
                                "LastRead": "00 00 00", 
                                "NodeID": "01", 
                                "NewDeviceStatus": 2, 
                                "RSSI": 1.0, 
                                "Temperature": "e6 0a"
                                }
                            }
                        }'''
            inqueue.put(1,another_big_test);


            # connect the websocket to its target on the internet.
            ws.connect()
            # prepare the mainloop
            mainLoop = tornado.ioloop.IOLoop.instance()
            # add scheduler to mainloop before starting it.
            scheduler_interval = 100 #ms? 
            scheduler = tornado.ioloop.PeriodicCallback(ws.checkQueue, scheduler_interval, io_loop = mainLoop)
            scheduler.start()
            # start it all
            mainLoop.start()


            print("DEMO---------------------- WARNING mainLoop WARNING ----------------------");
            print("DEMO--------- this is the PORTAL CLIENT restarting unexpectably.  -----------");
            print("DEMO---------------------- WARNING mainLoop WARNING ----------------------");


            # just to be sure we've fully cloase the WS 
            try:
                #ws.close()
                ws.close_connection()
                ws.closed(99)
            except BaseException as e:
                print "close error"

            # after the WS is dropped, we'll sleep before retrying
            time.sleep(backoff);
            backoff = backoff*2
            # max delay before retry is 1hr. 
            if backoff > 3600:
                backoff = 3600
