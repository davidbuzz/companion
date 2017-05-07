# run then browse to http://127.0.0.1:8888/
# http://en.proft.me/2014/05/16/realtime-web-application-tornado-and-websocket/ 
from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.httpserver
 
import json
import setproctitle

from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping
from file_utils import read_passwd_file, file_get_contents, file_put_contents, read_config,write_config,read_master_wifi,write_new_master

import sys  # for sys.platform win32 vs linux test
from multiprocessing import Process
import multiprocessing
import time
import os 

from SimplePriorityQueue import SimplePriorityQueue


tensecond = 0


# see also
# complex https://github.com/hfaran/Tornado-JSON/blob/master/docs/using_tornado_json.rst
# simple https://gist.github.com/mminer/5464753
# tornado howto http://www.tornadoweb.org/en/stable/guide/structure.html
#and http://fabacademy.org/archives/2015/doc/WebSocketConsole.html


from tornado.options import define, options, parse_command_line

#if sys.platform == 'win32':
#define("port", default=8888, type=int)
#else:
#    define("port", default=80, type=int)


# all this does is take the index html file (index.template.html) from on-disk, populate it with some variables from the JSON file, and 
# send it to the user and their browser. 
class IndexHandler(tornado.web.RequestHandler):

    def get(self):
        config = read_config()
        vars = read_master_wifi()

        
        #we blank these for now, unneeded but still in template. 
        config['portal1'] = '';
        config['portal2'] = '';
        config['failtime'] = '';
        config['majorversion'] = '';
        config['minorversion'] = '';
        self.render("index.template.html", PORTAL1 = config['portal1'] , PORTAL2 = config['portal2'], 
            SSID1 = config['ssid1'] , SSID2 = config['ssid2'] , PASSWORD1 = config['pwd1'],
            PASSWORD2 = config['pwd2'], 
            FAILOVERTIME = config['failtime'],
            BASICAUTH =  config['basicauth'],
            MAJORVERSION = config['majorversion'],
            MINORVERSION = config['minorversion'],
            CURRENTWIFI = vars['mssid'] )

def ws_start_wifi_test():

            # this will eventually run cron_reader_thread's start_wifi_test() call.... , but from a different 'cron' thread, not the tornado server.
            j = {}
            j['WIFITEST'] = 'begin' 

            #and finally, we handle this special stil-wrapped format in portalclient, so pass it there....
            goutq.put(1,json_wrap_with_target(j,'slowserver')) 

            #j = {}
            #j['WIFISTATUS']={}
            #j['WIFISTATUS']['color'] = color
            #j['WIFISTATUS']['response'] = msg



class WebSocketHandler(tornado.websocket.WebSocketHandler):
    waiters = set()    # list of connections current, stored in the class, not the object! 

    @classmethod
    def send_updates(cls, chat):
        #print("WebSocketHandler message: "+str(chat))
        #print("sending message to %d waiters" % len(cls.waiters))
        for waiter in cls.waiters:
            #try:
                waiter.write_message(chat)
            #except:
            #    print ("Error sending message to a client")
    
    def open(self, *args):
        print("New connection ")
        self.write_message("{ \"response\": \"http_server_open\" }") # goes only to THIS client.
        WebSocketHandler.waiters.add(self)   


    # THE POSSIBLE MESSAGE OPTIONS HERE:
    # 1 - config request from http client to disk
    # 2 - sim 1 request from http client to python WS client Q  ( pretending to be PORTAL instance sending data TO python WS)
    # 3 - sim 2 request from http client to python WS client Q  ( pretending to be router sending serial packet/s TO python WS  TBD)
    # 4 - sim 2 request from http client to python WS client Q  ( pretending to be router sending serial packet/s TO python WS  TBD)
    # 5 - logging data from the "main router" logging Q, to be pushed into the web browser for user display.
    # 

    def on_message(self, message):
        global goutq    # when we queue things to go to the central router from the tornado server, they go via this multiprocess queue...

        print("New message {}".format(message))

        #try:   # in case it's not actually JSON 
        json_data = json.loads(message)
        cleaned = json.dumps(json_data,indent=2,sort_keys=True)      
        #except: 
        #    err = "not valid JSON, sorry"
        #    WebSocketHandler.send_updates(err) # goes to all clients, not just one: self.write_message(err)
        #    return

        # dispatch based on where the JSON reports to have come from ( might not be true ) 
        src = ''
        if ('src' in json_data):
            src = json_data['src']

        # quick validate if 'data' is there, its also OK for it not to be there at all.
        if  ('data' in json_data):
                    if json_data['data'] ==  "This is where you can paste JSON if you want.\n":   # that's its default
                        err = "You need to enter some valid JSON first."
                        self.write_message(err) # just to this client, not others.
                        return

        # someone pressed the "test wifi" button on the index.html web page. 
        if (src == "testwifi"): 

                #  write it into the format of JSON to start, that's not really going to block much...
                if sys.platform == 'win32':
                    dirname = 'X:\\WebConfigServer\\tools\\'
                    filename =  dirname+'masterwifi.windows.json'
                else:
                    dirname = '/root/WebConfigServer/tools/'
                    filename =  dirname+'masterwifi.json'

                # takes whatever is in the config file in ssid1 and pwd1, and uses them, ignores what we sent it. 
                write_new_master(1) # is the better way to do it

                msg = "testing wifi, please wait up-to 30 seconds for a response below ...!:"
                print msg
                j = {}
                j['response'] = msg 
                WebSocketHandler.send_updates(j) 

                ws_start_wifi_test()

                color = "#ffdb4d" # it's a bright "orange"  for in-progress...
                msg = "wifi test begun OK...working..."

                print msg
                j = {}
                j['WIFISTATUS']={}
                j['WIFISTATUS']['color'] = color
                j['WIFISTATUS']['response'] = msg

                WebSocketHandler.send_updates(j) 


             # normal interaction with the webpage <send> button, for anything EXCEPT JSON data in the 'data' field.
        if (src == "webpage"):  # that's the JSON from the "Save Settings" button on the index.html web page
                # we write the JSON to a config file for now. 
                # 

                msg = "Wrote data to WebConfigServer.json config file!:" 
                write_config(json_data) # we pass it in as JSON so the write_config() can peek at it too. 
                    

                # we'll also (optional ) push the cleaned JSON back to the client to tell them we got it OK, with a proper 'response' message to follow below to explain it. 
                WebSocketHandler.send_updates(cleaned) # goes to all clients, not just one: self.write_message(cleaned)

                # when the things run on LINUX with a RO filesystem, we need a way to persist this over reboots. - maybe a tiny /persist filesystem, with just this in it? 
                print msg
                # report it back the the web broswer  to tell them we got it OK:
                j = {}
                j['response'] = msg 

                # if done from anywhere excpet the local webserver itself, this would be called like this:
                #goutq.put(1,json_wrap_with_target(j,'logging')) 
                # instead it's like this:
                WebSocketHandler.send_updates(j) # goes to all clients, not just one:  self.write_message(j)
                return


        # SIMULATE data coming FROM the PORTAL server TO the python client. ( injected into the client as if it canme from the server) 
        # or SIMULATE data coming FROM the python client that goes TO the real PORTAL server, ( ie injected into the client as if it is about to go TO the server) 
        # all we're really doing here is passing the appropriate message onward to it's destination and logging it. 
        if (src == "portalsimulserver") or (src == "portalsimulclient"):  # that's the JSON from one of the 'data' fields on the index.html web page  - it's for debug 
                                    # and is for JSON that should arrive from PORTAL, but we allow to arrive from the browser:
                #try:
                    j ={}
                    j['response']="simulated portal client/server message passed on to portal client..."

                    # tell user the simulated request was recieved....
                    WebSocketHandler.send_updates(j)
                    # it came from the browser to the local tornado server, but its got to go further... to the main router as well...
                    # if done from anywhere excpet the local webserver itself, this would be called like this:
                    #goutq.put(1,json_wrap_with_target(json_data,'logging')) 

                    # this logs the contents of the simulation request for review...
                    WebSocketHandler.send_updates(json_data) # goes to all clients, not just one: self.write_message(json_data)

                    #and finally, we handle this special stil-wrapped format in portalclient, so pass it there....
                    goutq.put(1,json_wrap_with_target(json_data,'portalclient')) 

                #except:
                #    err = "Sorry, that doesn't look like valid JSON in the 'data' field."
                #    self.write_message(err)  # error goes just to this client.
                #    return
                #    # probably not json, tell them its bad. 


    def on_close(self):
        print("Connection closed")
        WebSocketHandler.waiters.remove(self)




app = tornado.web.Application([
    (r'/', IndexHandler),
    (r'/ws/', WebSocketHandler),
#   (r"/(.*)", tornado.web.StaticFileHandler, {"path": os.path.dirname(__file__), "default_filename": "index.html"} ),
    (r"/static/(.*)", tornado.web.StaticFileHandler, {"path":os.path.join(os.path.dirname(__file__), "static") }  ),
#    (r'/index\.html$', tornado.web.StaticFileHandler, dict(path=settings['static_path'])),
])

#clients = [] 
#WebSocketHandler.waiters
ginq = None
goutq = None

## check the queue for pending messages, and rely that to all connected clients
def checkQueue():
    #print("tornado checking queue")
    global ginq
    global goutq
    global tensecond

    if not ginq.empty():
        message = ginq.get()
        #for c in WebSocketHandler.waiters.:
        #    c.write_message(message)
        #print("Got a message from the queue to tornado....")
        WebSocketHandler.send_updates(message)   # sends to all WS clients that are connected.

    now = int(time.time())

    # 10 second loop.
    if now > tensecond+10: # we post idle message at least every 10 secs
        tensecond = now   # see below...
        print "tornado loop is idling"
        ## ping central thread to tell them we are still here...
        queue_ping(goutq,'webserver')


def webmain(inq, outq):
    global ginq
    global goutq
    ginq = inq  
    goutq = outq
    print("Starting Tornado HTTP and WebSockets enabled server on https://127.0.0.1 and other local IPs")
    # simple, but no callbacks:
    #    app.listen(options.port)
    #    tornado.ioloop.IOLoop.instance().start()
    # OR: 
    # with callback support: 
    httpServer = tornado.httpserver.HTTPServer(app, ssl_options = { "certfile": os.path.join("certs/certificate.pem"),  "keyfile": os.path.join("certs/privatekey.pem")}  )
    httpServer.listen(4443)
    print("Listening on port:", 443)
    mainLoop = tornado.ioloop.IOLoop.instance()
    ## adjust the scheduler_interval according to the frames sent by the serial port
    scheduler_interval = 10 #ms? 
    scheduler = tornado.ioloop.PeriodicCallback(checkQueue, scheduler_interval, io_loop = mainLoop)
    scheduler.start()
    mainLoop.start()

# if requested to start from multiprocess module, spinup this way in it's own process.
class WebAndSocketServer(Process):
        def __init__(self, web_input_queue, web_output_queue):
            self.input_queue = web_input_queue
            self.output_queue = web_output_queue
            Process.__init__(self)
            pass

        def run(self):
            #with modified_stdout("TORNADO> ", logfile='WebConfigServer_tornado.log'):
                sys.stdout = CustomPrint(sys.stdout,"TORNADO> ","WebConfigServer_tornado.log")
                print("starting webserver in own process, thx.")
                proc_name = self.name
                pid = os.getpid()
                setproctitle.setproctitle("APSync Tornado")
                print("Starting: %s process with PID: %d " % (proc_name, pid))

                webmain(self.input_queue,self.output_queue)  # passing input and output queue/s from object into non-object call.
                pass


# if called directly from the cmd line, just start the web server stand-alone.
if __name__ == '__main__':
    print("starting webserver standalone... thx.")
    input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()      # we send data TO the local HTTP and websockets process
    output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()     # get from 
    webmain(input_queue,output_queue)

