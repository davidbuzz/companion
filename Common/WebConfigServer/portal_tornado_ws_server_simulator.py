

# run then browse to https://127.0.0.1:9999/
# note that  the PORTAL simulator is where we can toggle into and out of demo mode.   https://apsync.local:9999/  see "Demo mode: 1 "

# http://en.proft.me/2014/05/16/realtime-web-application-tornado-and-websocket/ 
from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.httpserver
 
import json
from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping,log_to_file
from file_utils import read_passwd_file, file_get_contents, file_put_contents

import sys  # for sys.platform win32 vs linux test
from multiprocessing import Process
import multiprocessing
import time
import os
import setproctitle
from SimplePriorityQueue import SimplePriorityQueue


# see also
# complex https://github.com/hfaran/Tornado-JSON/blob/master/docs/using_tornado_json.rst
# simple https://gist.github.com/mminer/5464753
# tornado howto http://www.tornadoweb.org/en/stable/guide/structure.html
#and http://fabacademy.org/archives/2015/doc/WebSocketConsole.html

#DO_ALL_DEVICES = True

# global for demo state, start by assuming NO demo
demo = 0   

# global for
desireddevicestates = {}
devicelist = {}

# is it? 
is_highalert = 0
is_standby = 0
is_network_reset = 0
is_green = 0
is_red = 0

# should tell us from FeatureHandler what/s on or off...
mydb = {'demo':0,'highalert':0,'standby':0,'networkreset':0,'green':0,'red':0 }

ginq = None
goutq = None

from tornado.options import define, options, parse_command_line

define("portalport", default=9999, type=int)

import base64
#import netaddr
#import bcrypt

# this overrides the _execute() function of the WebSocketHandler so it can support basic auth without hte need to create a full subclass...  neat. 
def require_basic_auth(handler_class):
    """ auth decorator see:
        http://kevinsayscode.tumblr.com/post/7362319243/easy-basic-http-authentication-with-tornado
    """
    def wrap_execute(handler_execute):
        def require_basic_auth(handler, kwargs):
            auth_header = handler.request.headers.get('Authorization')
            if auth_header is None or not auth_header.startswith('Basic '):
                handler.set_status(401)
                handler.set_header('WWW-Authenticate', 'Basic realm=Restricted')
                handler._transforms = []
                handler.finish()
                return False
            auth_decoded = base64.decodestring(auth_header[6:])
            kwargs['basicauth_user'], kwargs['basicauth_pass'] = auth_decoded.split(':', 2)
            return True
        def _execute(self, transforms, *args, **kwargs):
            if not require_basic_auth(self, kwargs):
                return False
            return handler_execute(self, transforms, *args, **kwargs)
        return _execute
    handler_class._execute = wrap_execute(handler_class._execute)
    return handler_class


def verify_password(passwords, username, password):
    #hashed = bcrypt.hashpw(password, bcrypt.gensalt(12))
    #stored_hash = passwords[username].strip("\n")
    #if stored_hash == bcrypt.hashpw(password, stored_hash):
    try:
        if passwords[username] == password:
            return True
        else:
            return False
    except:
        print("verify_password failed, probably a non-existant user")
        return False


class FeatureHandler(tornado.web.RequestHandler):
    def initialize(self, db):
        self.db = db

    def get(self):
        #self.write("this is feature %s" % feature_id)
        #self.db['demo_id'] = 1
        # you can also access self.request here.
        # and thus self.request.query, self.request.uri, self.request.path, and more
        self.db['demo'] = int(self.get_argument('demo'))
        self.db['highalert'] = int(self.get_argument('highalert'))
        self.db['standby'] = int(self.get_argument('standby'))
        self.db['networkreset'] = int(self.get_argument('networkreset'))
        self.db['green'] = int(self.get_argument('green'))
        self.db['red'] = int(self.get_argument('red'))

        print repr(self.db)


    def set_extra_headers(self, path):
        self.set_header("Cache-control", "no-cache")   


class IndexHandler(tornado.web.RequestHandler):
    def initialize(self, db):
        self.db = db
        if not 'demo' in self.db:
            self.db['demo'] = 0
        if not 'highalert' in self.db:
            self.db['highalert'] = 0
        if not 'standby' in self.db:
            self.db['standby'] = 0
        if not 'networkreset' in self.db:
            self.db['networkreset'] = 0
        if not 'green' in self.db:
            self.db['green'] = 0
        if not 'red' in self.db:
            self.db['red'] = 0

    def get(self):

        print repr(self.db)

        global demo

        # flip the demo if requested to..
        if self.db['demo'] == 1:
              #demo = 1
              print "in demo mode"
        else:
              #demo = 0
              print "not in demo mode"


        self.render("portalindex.html", DEMO = self.db['demo'], ALERT = self.db['highalert'] , STBY = self.db['standby'], RESET = self.db['networkreset']  , RED = self.db['red']  , GREEN = self.db['green']  )


    def set_extra_headers(self, path):
        self.set_header("Cache-control", "no-cache")

# https://gist.github.com/fliphess/7836469  for basic auth on tornado

@require_basic_auth
class PORTALWebSocketHandler(tornado.websocket.WebSocketHandler):
    waiters = set()    # list of connections current, stored in the class, not the object! 
    #devicelist = {}   # wehre we cache the devices we know about, so we can do acknowledgements properly, with repeats ( actual node state )
    #desireddevicestates = {}   # whre we cache the device states we WANT the nodes to have

    def get(self, basicauth_user, basicauth_pass):
        passwords = read_passwd_file()
        if verify_password(passwords,basicauth_user,basicauth_pass):
            tornado.websocket.WebSocketHandler.get(self)
            #self.write("Hello, authenticated user")
        else:
            #self.write("Hello, authenticated user")
            self.set_status(404)
            self.finish('authentication error')
            pass
            

    @classmethod
    def send_updates(cls, chat):
        print("PORTALWebSocketHandler message: "+str(chat))
        print("sending message to %d waiters" % len(cls.waiters))
        if len(cls.waiters) != 1:
            print("---------------------- WARNING WARNING WARNING ----------------------");
            print("--- INCORRECT NUMBER OF CLIENT CONNECTED - EXPECTED EXACTLY ONE. ----");
            print("---------------------- WARNING WARNING WARNING ----------------------");
        for waiter in cls.waiters:
            #try:
                #log_to_file(".server.OUT.json",str(chat))
                waiter.write_message(chat)
            #except:
            #    print ("Error sending message to a client")
    
    def open(self, *args):

        print("New connection ")
        message = "{ \"response\": \"portal_server_open\" }"
        #log_to_file(".server.OUT.json",message)
        self.write_message(message)
        PORTALWebSocketHandler.waiters.add(self)   




    def on_message(self, message):
        global devicelist
        global desireddevicestates

        #print("GOT New message {}".format(message))

        json_data = {}
        #try:   # in case it's not actually JSON 
        json_data = json.loads(message)
        cleaned = json.dumps(json_data,indent=2,sort_keys=True)      
        #except: 
        #    err = "not valid JSON, sorry"
        #    self.write_message(err)
        #    json_data = {}
        #    return

        print repr(json_data)

        #log_to_file(".server.IN.json",message)

        # what possible INCOMING PORTAL packets are there..? 
        if ('DeviceUpdate' in json_data):

            ## here we just save all DeviceChange messages that come to us...
            # note that the json for DeviceUpdate and DeviceChange is a tiny bit different, so witing them both to devicelist is probably bad.
            #for mac in json_data['DeviceUpdate']:
            #        #ok["AcknowledgedDeviceUpdate"][mac] = json_data['DeviceUpdate'][mac];       
            #        # we locally save the entire changed info for that MAC, mostly we are interested in 'NewDeviceStatus', but others are interesting.
            #        devicelist[mac] = json_data['DeviceUpdate'][mac]    # ['NewDeviceStatus']   

            ok = {}
            ok['status'] =  "OK"
            ok["other"] = "simulated portalserver handled this DeviceUpdate message"
            PORTALWebSocketHandler.send_updates(ok)

        # this packet needs to be properly Acknowledged, in-particular the fact that if this packet isn't properly acknowledged back to the 
        # Linux GW, and the Node that sent it has had it's NewDeviceStatus field change, then it won't go from un-acknowledged to acknowledged ( from blinking green or red to solid ) 
        if ('DeviceChange' in json_data):
            ok = {}
            ok['status'] =  "OK"
            ok["other"] = "simulated portalserver handled this DeviceChange message"
            ok["AcknowledgedDeviceStatus"] = {}

            # unacknowledged ( for example) green pulsing, needs acknowledgement to go solid green if we weren't already in that state 
            # by sending back the NewDeviceStatusID with the value of the "last seen" NewDeviceStatus field we 
            # can consider it properly acknowledged. 

            # here we just acknowledge all DeviceChange messages that come to us...
            for mac in json_data['DeviceChange']:
                    ok["AcknowledgedDeviceStatus"][mac] = json_data['DeviceChange'][mac];       

                    # also we'll locally save the entire changed info for that MAC, mostly we are interested in 'NewDeviceStatus', but others are interesting.
                    devicelist[mac] = json_data['DeviceChange'][mac]    # ['NewDeviceStatus']

                    # if desired:ff:ff:ff:ff:ff:ff->X, then push all discovered MACs into the 'desired' list individually too.
                    # we only retry states 2 and 4 as these are individually addresses,  not 1 and 0 as the serial handles these.
                    if ('ff:ff:ff:ff:ff:ff' in desireddevicestates) and \
                        ( (desireddevicestates['ff:ff:ff:ff:ff:ff'] == "2") or (desireddevicestates['ff:ff:ff:ff:ff:ff'] =="4" )) :
                            desireddevicestates[mac] = desireddevicestates['ff:ff:ff:ff:ff:ff']


            PORTALWebSocketHandler.send_updates(ok)

        # this is a "OK, thanks, I got it"  response to other packets.
        if ('Status' in json_data):
            pass

        # this is a "OK, thanks, I got it"  response to other packets.
        if ('Ping' in json_data):
            ok = {}
            ok['status'] =  "ok"
            ok["other"] = "simulated portalserver handled this Ping message"
            PORTALWebSocketHandler.send_updates(ok)


    def on_close(self):
        print("Connection closed")
        PORTALWebSocketHandler.waiters.remove(self)

        
    @classmethod
    def issue_AllClear(self):
        print "issue_AllClear()"

        global devicelist
        global desireddevicestates

        #global DO_ALL_DEVICES
        s = '''{
          "AllClear":[
             "aa:bb:cc:dd:ee:ff",
             "aa:bb:cc:dd:ee:ee",
             "ff:ee:dd:cc:bb:aa",
             "aa:bb:cc:dd:ee:aa"
          ]
        }'''
        j = json.loads(s)
        #if DO_ALL_DEVICES:
        j['AllClear'].append("ff:ff:ff:ff:ff:ff")

        # record the desired individual state/s  
        for mac in j['AllClear']:
            desireddevicestates[mac] = "0"

        # we'll flip the state of every device we know about....
        if "ff:ff:ff:ff:ff:ff" in j['AllClear']:
            for mac in desireddevicestates:
                desireddevicestates[mac] = "0"

        # and then remove ff:ff:ff: etc from the device list..... 
        if "ff:ff:ff:ff:ff:ff" in desireddevicestates:
            del desireddevicestates["ff:ff:ff:ff:ff:ff"]
        if "ff:ff:ff:ff:ff:ff" in devicelist:
            del devicelist["ff:ff:ff:ff:ff:ff"]

        # issue the all clear to all currtently connected clients! 
        PORTALWebSocketHandler.send_updates(j)
        
    @classmethod
    def issue_ChangeStatus(self,status):
        print "issue_ChangeStatus()"

        global devicelist
        global desireddevicestates

        if status == 2:
            is_green = 1
            is_red = 0
        if status == 4:
            is_red = 1
            is_green = 0

        s = '''{
              "ChangeStatus":{ 
                 "aa:bb:cc:dd:ee:ff":  "4",
                 "aa:bb:cc:dd:ee:cc":  "4",
                 "ff:ee:dd:cc:bb:aa":  "'''+str(status)+'''",
                 "aa:bb:cc:dd:ee:aa":  "4"
              }
            }'''
#                 "eb:4f:80:b6:6a:e7":  "'''+str(status)+'''",
        j = json.loads(s)
        #if DO_ALL_DEVICES:
        j['ChangeStatus']["ff:ff:ff:ff:ff:ff"] = str(status)

        # record the desired individual state/s ( TODO sort out the ff:ff issue ) 
        for mac in j['ChangeStatus']:
            desireddevicestates[mac] = j['ChangeStatus'][mac]

        # handle the ff:ff issue by recording that we want ALL the nodes we know about to change to this status, if ff:ff is there
        if "ff:ff:ff:ff:ff:ff" in j['ChangeStatus']:
            # set the nodes we know about....
            for mac in devicelist:
                desireddevicestates[mac] =  j['ChangeStatus']["ff:ff:ff:ff:ff:ff"]
            # and the ones we don't...
            for mac in desireddevicestates:
                desireddevicestates[mac] =  j['ChangeStatus']["ff:ff:ff:ff:ff:ff"]

        # and then remove ff:ff:ff: etc from the device list..... 
        if "ff:ff:ff:ff:ff:ff" in desireddevicestates:
            del desireddevicestates["ff:ff:ff:ff:ff:ff"]
        if "ff:ff:ff:ff:ff:ff" in devicelist:
            del devicelist["ff:ff:ff:ff:ff:ff"]

        # issue the status change to all currtently connected clients! 
        PORTALWebSocketHandler.send_updates(j)
        
    @classmethod
    def issue_HighAlert(self):
        print "issue_HighAlert()"
        global devicelist
        global desireddevicestates


        s = '''{
          "HighAlert":[
             "ff:ff:ff:ff:ff:ff"
          ]
        }'''
        j = json.loads(s)
 

        # record the desired individual state/s
        for mac in j['HighAlert']:
            desireddevicestates[mac] = "0"

        # we'll flip the state of every device we know about... and the ones we dont...
        if "ff:ff:ff:ff:ff:ff" in j['HighAlert']:
            for mac in devicelist:
                desireddevicestates[mac] = "0"
            for mac in desireddevicestates:
                desireddevicestates[mac] = "0"

        # and then remove ff:ff:ff: etc from the device list..... 
        if "ff:ff:ff:ff:ff:ff" in desireddevicestates:
            del desireddevicestates["ff:ff:ff:ff:ff:ff"]
        if "ff:ff:ff:ff:ff:ff" in devicelist:
            del devicelist["ff:ff:ff:ff:ff:ff"]
            
        # issue the msg to all currtently connected client/s! 
        PORTALWebSocketHandler.send_updates(j)

    @classmethod
    def issue_NetworkReset(self):
        print "issue_NetworkReset()"
        global devicelist
        global desireddevicestates


        s = '''{
          "NetworkReset":[
             "ff:ff:ff:ff:ff:ff"
          ]
        }'''
        j = json.loads(s)


        # record the desired individual state/s
        for mac in j['NetworkReset']:
            desireddevicestates[mac] = "0"

        # we'll flip the state of every device we know about... and the ones we dont...
        if "ff:ff:ff:ff:ff:ff" in j['NetworkReset']:
            for mac in devicelist:
                desireddevicestates[mac] = "0"
            for mac in desireddevicestates:
                desireddevicestates[mac] = "0"

        # and then remove ff:ff:ff: etc from the device list..... 
        if "ff:ff:ff:ff:ff:ff" in desireddevicestates:
            del desireddevicestates["ff:ff:ff:ff:ff:ff"]
        if "ff:ff:ff:ff:ff:ff" in devicelist:
            del devicelist["ff:ff:ff:ff:ff:ff"]
            
        # issue the msg to all currtently connected client/s! 
        PORTALWebSocketHandler.send_updates(j)


    #@classmethod
    #def issue_bad_json(self):
    #    s = '''{
    #         "XXXX":{ }}}
    #        }'''
    #    try:
    #        j = json.loads(s)
    #        # issue the status change to all currtently connected clients! 
    #        PORTALWebSocketHandler.send_updates(j)
    #    except:
    #        print "cant issue syntactically JSON, sorry"



from tornado.web import url



app = tornado.web.Application([
    url(r'/', IndexHandler, dict(db=mydb)),
    (r'/ws/', PORTALWebSocketHandler),
    (r"/static/(.*)", tornado.web.StaticFileHandler, {"path":os.path.join(os.path.dirname(__file__), "static") }  ), # for jquery 
    url(r"/feature/", FeatureHandler, dict(db=mydb)),
])

#clients = [] 
#PORTALWebSocketHandler.waiters

atstart = None
tensecond = None
thirtysecond = None

recentdone = 0

## check the queue for pending messages, and rely that to all connected clients
# this is called REPEATEDLY, every 100ms....
def checkQueue():
    #print("tornado checking queue")
    global ginq
    global goutq
    global atstart
    global recentdone
    global demo
    global devicelist
    global desireddevicestates
    global tensecond
    global thirtysecond
    global is_highalert
    global is_standby
    global is_network_reset
    global is_green
    global is_red

    now = int(time.time())

    # init the time/s. 
    if atstart == None:
        atstart=now
        recentdone = 0
        tensecond = now
        thirtysecond = now

    # 10 second loop.
    if now > tensecond+10: # we post idle message at least every 10 secs
        tensecond = now   # see below...
        print "portalsimulator loop is idling"
        ## ping central thread to tell them we are still here...
        queue_ping(goutq,'portalwebserver')



    #every 30 seconds, if the desired device state is not the same 
    #as the actual state in the devicelist, resent request to chnge state
    if ( (is_red == 1) or (is_green == 1) or (demo == 1) ) and ( now > thirtysecond +30 ) :

            thirtysecond = now

            #print "ChangeStatus ReTrX:\n"
            status = 0 # for the test address below... otherwise ignored.
            s = '''{
                    "ChangeStatus":{ 
                    }
                }'''
            j = json.loads(s)
        
            # now we are going to try to re-do the ChangeStatus request for all nodes that we think are in the wrong state
            # noting that we can only change devices with a status of 2 or 4 ( as other states like 0 and 1 are not done like this) 
            #print repr(desireddevicestates)
            for m in desireddevicestates:
                if (desireddevicestates[m] == "2") or ( desireddevicestates[m] == "4"):
                    try:
                        if str(devicelist[m]['NewDeviceStatus']) != str(desireddevicestates[m]):  # one dict is a string, so compare both that way.
                            j['ChangeStatus'][m] =  desireddevicestates[m]
                            #print "totallyam retrying to change state of :"+str(m)+" to state:"+str(desireddevicestates[m] )
                    except KeyError as e: # ignore keys we don't know about
                        pass
                else:
                    #print "not retrying to change state of: "+str(m)+" to state:"+str(desireddevicestates[m] )
                    pass


            if j['ChangeStatus']: # empty dict evaluates to False in python, so we don't wase time sending empty messages...
                # issue the status change to all currtently connected clients! 
                PORTALWebSocketHandler.send_updates(j)

            #tensecond = now

    # respond to actionable requests from the portalindex.html page.. which is passed to us via the mydb global doctionary.
    global mydb

    #print repr(mydb)
    # 

    if ( mydb['demo'] == 1 ) and ( demo != 1 ) :
        print "going into DEMO mode!!!!!"
        demo = 1
        is_standby = 0
        is_highalert = 0
        is_network_reset = 0
        is_green = 0
        is_red = 0
        thirtysecond = now
        atstart = now
        recentdone = 0

    if ( mydb['demo'] == 0 ) and ( demo != 0 ) :
        demo = 0
        print "going OUT of DEMO mode!!!!!"
        is_standby = 0
        is_highalert = 0
        is_network_reset = 0
        is_green = 0
        is_red = 0

    if ( mydb['standby'] == 1 ) and ( is_standby != 1 ) :
        print "going into standby mode!!!!!"
        PORTALWebSocketHandler.issue_AllClear() 
        is_standby = 1
        is_highalert = 0
        is_network_reset = 0
        is_green = 0
        is_red = 0
        demo = 0

    if ( mydb['highalert'] == 1 ) and ( is_highalert != 1 ) :
        print "going into high alert mode!!!!!"
        PORTALWebSocketHandler.issue_HighAlert() 
        is_standby = 0
        is_highalert = 1
        is_network_reset = 0
        is_green = 0
        is_red = 0
        demo = 0

    if ( mydb['networkreset'] == 1 ) and ( is_network_reset != 1 ) :
        print "going into networkreset mode!!!!!"
        PORTALWebSocketHandler.issue_NetworkReset() 
        is_standby = 0
        is_highalert = 0
        is_network_reset = 1
        is_green = 0
        is_red = 0
        demo = 0
    if ( mydb['green'] == 1 ) and ( is_green != 1 ) :
        print "going into GREEN mode!!!!!"
        PORTALWebSocketHandler.issue_ChangeStatus(2) 
        is_standby = 0
        is_highalert = 0
        is_network_reset = 0
        is_green = 1
        is_red = 0
        demo = 0
    if ( mydb['red'] == 1 ) and ( is_red != 1 ) :
        print "going into RED mode!!!!!"
        PORTALWebSocketHandler.issue_ChangeStatus(4) 
        is_standby = 0
        is_highalert = 0
        is_network_reset = 0
        is_green = 0
        is_red = 1
        demo = 0
 
    # if we are in the demo cycle..
    if demo == 1:
        end=time.time()

        secs_in_minute = 60

        # minutes: 1 2 6 10
        # minutes: 1 2 5 8

        # chuck a few items out of the simulated PORTAL server for the system/s to respond to. 
        if end-atstart > secs_in_minute*1 and recentdone == 0:
            # nothing here, go to next one
             recentdone = recentdone +1 

        if end-atstart > secs_in_minute*2 and recentdone == 1 :  
            print "PORTALWebSocketHandler.issue_ChangeStatus(2)"
            PORTALWebSocketHandler.issue_ChangeStatus(2)   # unacknowledged , blinking green
            recentdone = recentdone +1 

        if end-atstart > secs_in_minute*5 and recentdone == 2 :          
            print "PORTALWebSocketHandler.issue_ChangeStatus(4)"
            PORTALWebSocketHandler.issue_ChangeStatus(4)    # unacknowledged, blinking red
            #as a simulator, we are dumb and don't pay attention to the actual NewDeviceStatus data, so do a dump "retry"
            recentdone = recentdone +1 

        if end-atstart > secs_in_minute*8 and recentdone == 3:
            print "PORTALWebSocketHandler.issue_AllClear()"
            PORTALWebSocketHandler.issue_AllClear()
            recentdone = recentdone +1 

            print "PORTALWebSocketHandler timer start over."
            atstart = end   # start over.
            recentdone = 0


def portalwebmain(inq, outq):
    global ginq
    global goutq
    ginq = inq  
    goutq = outq
    print("Starting SECURE PORTAL Tornado HTTP and WebSockets enabled server on https://127.0.0.1:9999 with wss:// support")
    # simple, but no callbacks:
    #    app.listen(options.portalport)
    #    tornado.ioloop.IOLoop.instance().start()
    # OR: 
    # with callback support: 
    httpServer = tornado.httpserver.HTTPServer(app,  ssl_options = { "certfile": os.path.join("certs/certificate.pem"),  "keyfile": os.path.join("certs/privatekey.pem")})
    httpServer.listen(options.portalport)
    print("Listening on port:", options.portalport)
    mainLoop = tornado.ioloop.IOLoop.instance()
    ## adjust the scheduler_interval according to the frames sent by the serial port
    scheduler_interval = 20 #ms? 
    scheduler = tornado.ioloop.PeriodicCallback(checkQueue, scheduler_interval, io_loop = mainLoop)
    scheduler.start()
    mainLoop.start()

# if requested to start from multiprocess module, spinup this way in it's own process.
class PORTALWebAndSocketServer(Process):
        def __init__(self, sim_input_queue, sim_output_queue):
            self.input_queue = sim_input_queue  # unused.
            self.output_queue = sim_output_queue# just for pings.
            Process.__init__(self)
            pass

        def run(self):
            #with unmodified_stdout("SIMULATEDPORTAL> ", logfile='WebConfigServer_portal_sim.log'):
                sys.stdout = CustomPrint(sys.stdout,"SIMULATEDPORTAL> ","WebConfigServer_portal_sim.log")
                print("starting webserver in own process, thx.")
                proc_name = self.name
                pid = os.getpid()
                setproctitle.setproctitle("APSync PORTAL SIM")
                print("Starting: %s process with PID: %d " % (proc_name, pid))
                portalwebmain(self.input_queue,self.output_queue)  # passing input and output queue/s from object into non-object call.
                pass


# if called directly from the cmd line, just start the web server stand-alone.
if __name__ == '__main__':
    print("starting PORTAL webserver simulator... thx.")
    input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # unused..
    output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # just for pings.
    portalwebmain(input_queue,output_queue)

