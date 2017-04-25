from stdoutcontext import modified_stdout,unmodified_stdout,CustomPrint
import multiprocessing #.dummy
import serial
import sys
import os
#import threading
import time

import socket
#import queue  # 2.7->Queue 3.x->queue  a thread safe queueing for putting things to the ONE shared debug console from many threads
# TIP: for debugging "multiprocessing" with PTVS, need to manually connect to extra "python.exe" processes 
# see https://github.com/Microsoft/PTVS//125
# also 
#see https://docs.python.org/2/library/multiprocessing.html
from multiprocessing import Process, Queue
import binascii
import setproctitle

from serial_utils import  make_bytes_readable_hex,make_MAC_readable_hex,serial_receive,un_pretty,un_pretty_MAC
from struct import *    # unpack, pack etc 
import json
from json_utils import json_wrap_with_target,json_unwrap_with_target,queue_ping
from SimplePriorityQueue import SimplePriorityQueue


# copyright David "Buzz" Bussenschutt 2015, all rights reserved.
# bits from http://fabacademy.org/archives/2015/doc/WebSocketConsole.html

last_check_time = 0

# convenience function. current_milli_time()
current_milli_time = lambda: int(round(time.time() * 1000))


class SerialReaderWriter(Process):

    def __init__(self,  input_queue, output_queue, gDEVICES = {}, port='com23', baudrate=115200, parity='N', rtscts=True, xonxoff=False, echo=True, repr_mode=0):
        Process.__init__(self)
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.rtscts = rtscts
        self.STX=b'\02';  # start of packet x2
        self.ETX=b'\03';   # end of packet x1
        self.echo = echo
        self.repr_mode = repr_mode
        #self.Q = Queue() # from multithreading
        self.readerstring = b''    # its actually a bytearray, not a string... but whatever. 
        self.writestring = b''
        #self.ser = False
        self.alive = False   # assume we are NOT connected to start with, so it forces a re-connect.
        self.expecting_ack = False
        #print("expecting ack = False")
        self.smalldelay = 0.1
        self.gDEVICES =  gDEVICES  # device list, including the record of assigned NodeIDs and which MAC each is assigned to, and it's latest timestamp info, and more, in a hash
        self.packetstate = 0  # to begin the parser we look for an 'stx1' ( ie any stx in stream) 
        self.lastresettimestamp = 0  # time of most recent gateway reset DT_Alive
        self.device_list_start = None  # internal timer for knowing how often to send DEVICELIST2 messages see device_list_start
        self.device_list_prev = None   #
        self.startup_time =  time.time()   # this records the bootup time.... so after 30 seconds of bootup we drop to low power mode. 
        self.highstart = 0  # internal use.
        self.lowstart = 0
        self.midpacket = 0  # we set this to 1 while we are in the moddile of reading a packet....
        self.writeq = None
        #self.readq = None
        self.acknowledgement_handler_start = 0
        self.acknowledgement_handler_inprogress = 0
        self.acknowledgement_handler_done = 0
        self.acknowledgement_handler_data = b""
        self.acknowledgement_handler_goto_next = True # by default we assume we are NOT sending a packet right now
        self.acknowledgement_handler_retry_counter = 0
        self.packet_recieved = False
        self.acknowledgement_handler_expecting = False

        
    def run(self):
        global last_check_time
      #with modified_stdout("SERIAL_RW> ", logfile='WebConfigServer_serial.log'):
        sys.stdout = CustomPrint(sys.stdout,"SERIAL_RW> ","WebConfigServer_serial.log")
        proc_name = self.name
        pid = os.getpid()
        setproctitle.setproctitle("APSync SerialRW")
        print("Starting: %s process with PID: %d " % (proc_name, pid))

        if self.writeq == None:
            self.writeq = SimpleQueue()

        print(" waiting 5 secs for debugger to be attached manually")
        #time.sleep(5)
        backoff = 1
        self.ser = None

        # stay in this loop till we are connected properly.
        while (self.alive == False ) : 
            try:
                # a ZERO timeout means non-blocking on read/s.... writes are still blocking... unless writeTimeout is used.
                # timeout=0 means go into non-blocking mode, which IS IMPORTANT.  don't use Timeout=None, as that will HANG.
                self.ser = serial.serial_for_url(self.port, self.baudrate, parity='N', rtscts=self.rtscts, xonxoff=False, timeout=0)
                self.alive = True
            except AttributeError:
                # happens when the installed pyserial is older than 2.5. use the
                # Serial class directly then.
                self.ser = serial.Serial(port, baudrate, parity='N', rtscts=self.rtscts, xonxoff=False, timeout=0)
                self.alive = True
            except (serial.serialutil.SerialException, serial.SerialException) as e:
                    # catch serial.serialutil.SerialException from failing to open the serial port and tell buzz or something.
                    #print("\n\nOH DEAR, IT SEEMS WE CANT FIND THE USB-SERIAL DEVICE ( "+self.port+" ) AT THE MOMENT. ERROR!\n\t")
                    print(e)
                    print("LowHandler sleeping %s backoff seconds" % str(backoff))
                    # after the WS is dropped, we'll sleep before retrying
                    time.sleep(backoff);
                    backoff = backoff*2
                    # max delay before retry is 1 minute 
                    if backoff > 60:
                        backoff = 60
                    self.alive = False

            # if it's not a legit and current serial device, we can't go any further anyway.
            if self.ser == None:
                self.alive == False

        # if self.alive == True:  ( or if False  )
        # update the self.alive state in SerialPacketHandler.py
        #p = {}
        #p['self.alive'] = self.alive
        #self.output_queue.put(1,json_wrap_with_target(p,'serialpacket'))
            

        self.ser.flushInput()
        self.ser.flushOutput()

        # also implemented as gateway()
        print "sending ANOTHER initial gateway init packet"
        self.writeSerial(1,un_pretty("02 02 0C 00 F3 03"))

        # also send initial packt to put the serial into "HighAlert" mode for a bit...


        # tmp vars for holding the incompletely parsed packet that we are working on..
        currentpacketlengthlsb = 0
        currentpacketcommand = 0
        currentpacketdataamount = 0
        MAXSERIALPACKETLENGTH = 30

        try:
           while (self.alive == True ) :

                now = int(time.time())  # time in exact seconds

                # when processing the serial data, we'll attempt to read an entire packet before we do anything else ( such as these items ) 
                if ( self.midpacket == 0 ):
                    self.handle_data_from_incoming_queue() # as there is data in the queue to be handled. 
                    #time.sleep(0.01) # lower the cpu usage, take a tiny breath between each packet.TODO is this OK? 
                
                self.acknowledgement_handler() # low level serial handler for just acknowledgements

                self.write_queued() # push outstanding messages out the serial port if there are any, etc. 
                
                # HANDLE THE ( possible ) READING OF DATA
                data = self.ser.read(1)  # must be non-blocking.
                #bytesToRead = ser.inWaiting()

                # as we are non-blocking on reads, only handle the data if there is actually any:
                # this is the packet recieving state machine: 
                # using  self.packetstate as the state
                if len(data) != 0 : 
                    pass

                    #LOW LEVEL SERIAL DEBUG, uncomment these lines: 
                    ##DEBUG:
                    #print(make_bytes_readable_hex(data)),
                    ##DEBUG:
                    #print("state = "+str(self.packetstate))

                    #time.sleep(0.001) #just to prevent the CPU from hitting 100% just doing this thread - this is 1ms

                    ## STX1
                    #if (  self.packetstate == 0 ): 
                    #    # we are at the beginning of the packet, lets clear the previous data as it's obviously incomplete.
                    #    self.readerstring = '' # empty the string buffer.
                    #    currentpacketdataamount = 0  # reset the internal counters.
                    #    currentpacketlengthlsb = 0
                    #    currentpacketcommand = 0

                    #    if data == self.STX  :   # if the incoming byte is really the STX, that's awesome, 
                    #        self.readerstring = self.STX    # save it, and 
                    #        self.packetstate = 1    # move to the stx2 state

                    #        self.midpacket  = 1 # and remember that we are "in the middle of " reading a packet...
                    #    # else we stay in this state and keep looking for an STX.
                    #    continue

                    ## STX2
                    #if (  self.packetstate == 1 ):
              
                    #    #  we are NEAR the beginning of the packet, with just one STX seen so-far, if we get another STX, that's awesome.
                    #    if  data == self.STX  : 
                    #        self.readerstring = self.readerstring + self.STX
                    #        self.packetstate = 2    # move to the command state
                    #    else:
                    #        # we got something other than two stx's in a row, so we don't know what to do here other than fail, and go back to looking for a first stx again.
                    #         self.packetstate = 0
                    #    continue

                    ## command
                    #if (  self.packetstate == 2 ):
                    #    # add command byte to the packet, that's all for now.
                    #    self.readerstring = self.readerstring + data
                    #    currentpacketcommand = ord(data)
                    #    #future enhancement... check if the command byte is an actual valid/known one, and fail for anything else.
                    #    self.packetstate = 3    # move to the lengthlsb state
                    #    continue

                    ##lengthlsb
                    #if (  self.packetstate == 3 ):
                    #    # add lengthlsb byte to the packet, that's all for now.
                    #    self.readerstring = self.readerstring + data
                    #    currentpacketlengthlsb = ord(data)
                    #    # if there's expected to be data, go to that block, otherwise go to the checksum block
                    #    #DEBUG: print("expecting data block size of: %d" % currentpacketlengthlsb)
                    #    if currentpacketlengthlsb == 0  :
                    #        self.packetstate = 5    # move to the checksum state
                    #    else:
                    #        if currentpacketlengthlsb > MAXSERIALPACKETLENGTH: # overly long data block suggested, but we know that's not legit
                    #            self.packetstate = 0   # .. so we'll start over.
                    #        else:
                    #            self.packetstate = 4    # or if its ok, move to the data state
                    #    continue
                    ##  data
                    #if (  self.packetstate == 4 ):
                    #    # normally, we just append the data to the string buffer till weve got a complete packet.
                    #    self.readerstring = self.readerstring + data
                    #    currentpacketdataamount = currentpacketdataamount +1   # record how much data we've go so-far
                    #    #DEBUG:print("collecting data block size  currently: %d" % currentpacketdataamount)

                    #    if currentpacketdataamount >= currentpacketlengthlsb:  # if the amount we got exceeds the amount we are expecting, move to next state
                    #        self.packetstate = 5    # move to the crc state
                    #    continue

                    ## checksum 
                    #if (  self.packetstate == 5 ):
                    #    # add crc byte to the packet, that's all for now.
                    #    self.readerstring = self.readerstring + data
                    #    # we deliberately don't validate checksum here and fail the packet if not matching, so we can log packets that have wrong checksum.
                    #    self.packetstate = 6    # move to the etx state
                    #    continue

                    ##etx
                    #if (  self.packetstate == 6 ):
                    #    # when we are at the END of the packet , we wind it up
                    #    self.packetstate = 0    #we  move to the beginning state, no matter what, in this state.
                    #    if  data == self.ETX  : 
                    #        self.readerstring = self.readerstring + self.ETX

                    #        #self.Q.push(self.readerstring) # queue the entire packet for later handling.

                    #        if True: #for raw serial input debugging we log this as per client request.
                    #            print("RECVRAW<< "+make_bytes_readable_hex(self.readerstring))
    
                    #        self.midpacket  = 0 # and remember that we are no longer "in the middle of " reading a packet...

                    #        # is this an acknowledgement of receipt..?   we handle acknowledgements here, everything else in different module.

                    #        #if make_bytes_readable_hex(self.readerstring) == self.message_received():
                    #        if currentpacketcommand == 18: #same test as above, but easier...
                    #            #'MessageReceived' #0x12 = decimal 18
                    #            print "MessageReceived! (type 0x12 / 18) "
                    #            self.packet_recieved = True

                    #        else :
                    #            # we have the entire packet at this point, so we'll handlie it   y pushing it off to the 
                    #            # non-realtime process....
                    #            #print "GOT INCOMING PACKET!GOT INCOMING PACKET!GOT INCOMING PACKET!GOT INCOMING PACKET!" 
                    #            l = {}
                    #            l['incomingserialpacket'] = make_bytes_readable_hex(self.readerstring)
                    #            self.output_queue.put(1,json_wrap_with_target(l,'serialpacket'))

                    #        self.readerstring = '' # empty the string buffer.
                    #        data = ''
                    #    continue


                    # don't add any code to the while-true loop HERE, as there's LOTS of 'continue' statements that pre-empt the loop, and stop us getting here.
                    # add them at the start of the loop ( or at least b4 the state machine ) , not the end. 
        
        except (OSError, serial.SerialException, AttributeError) as e:
           print("whoops we've had an unrecoverable Serial port Exception.")
           self.alive = False
           print(e)
        # make this an infinite loop if we crash on a serial port error, we can re-open it! 
        self.run()
  

    # from external process into "write" queue...
    def handle_data_from_incoming_queue(self):

                # look for incoming request
                if not self.input_queue.empty():

                    print("Pulled JSON packet from queue for outbound to SERIAL...")
                    qdata = self.input_queue.get()

                    #print qdata
                    json_data = ''
                    try:   # in case it's not actually JSON 
                        json_data = json.loads(qdata)
                        cleaned = json.dumps(json_data,indent=2,sort_keys=True)     
                    except BaseException as e: 
                        err = "not valid JSON, sorry"+ str(e)
                        print err

                    #we could better handle the incorrect JSON data coming to us ( we should never recieve a 'response' only send it.
                    if ('writepacket' in json_data):
                        #self.print_pretty_sent_packet(un_pretty(json_data['writepacket']))
                        print repr(json_data)
                        self.writeSerial(json_data['priority'],un_pretty(json_data['writepacket']))
                        #self.print_pretty_sent_packet(json_data['writepacket'])
                        #self.writeSerial(1,json_data['writepacket'])

 
    # pass thru un_pretty() b4 sending it out the serial port...
    def ack(self):
        #ack packet:
        return "02 02 07 00 F8 03"

    # pass thru un_pretty() b4 sending it out the serial port...
    def gateway(self):
        #make it a gateway
        return "02 02 0C 00 F3 03"    #\F3 = 243, \0C = 12

    def message_received(self):
        return "02 02 12 00 ed 03"

    def network_reset(self):
        #  "Reset Devices" packet in 12-07-2016 spec at least.   
        return  "02 02 0E 00 F1 03"   # F1 = 241 
 


    def close(self):
        self.alive = False
        #self.ser.close()

    # any time we send out a message on serial, we need to retry sending it till we get a resonse or timeout.  we do this here...
    # this func is called very many times , very quickly, and does not ever loop or block itself. it's asyncish.
    def acknowledgement_handler(self):
        #        start = current_milli_time()
        #        progress = current_milli_time() # every 5ms
        #        done = start+100   # give up here.


        # we haven't seen any response:
        if  (self.packet_recieved == False):

            ##print "woot",
            self.acknowledgement_handler_inprogress = current_milli_time()

            x = self.acknowledgement_handler_inprogress - self.acknowledgement_handler_start
            y = self.acknowledgement_handler_retry_counter*16 # on average 16ms before each retry
            if (y > 0) and  (x >= y): 
                
                    print "x: y:"+str(x)+" "+str(y)
                    data = self.acknowledgement_handler_data
                    print "RETRYING("+str(self.acknowledgement_handler_retry_counter)+"):"
                    print "actual retry write"
                    self.ser.write(data)
                    self.acknowledgement_handler_retry_counter = self.acknowledgement_handler_retry_counter+1
                    self.acknowledgement_handler_expecting  = True 
                    #time.sleep(0.005) # 5ms


            ## we've exceeded alloted time slot of 100ms
            if (self.acknowledgement_handler_inprogress >= self.acknowledgement_handler_done) : 
                self.acknowledgement_handler_goto_next = True
                self.acknowledgement_handler_retry_counter = 0
                self.acknowledgement_handler_expecting = False
            #    pass
 
            if self.acknowledgement_handler_retry_counter > 20:   # 20 retrties in 100ms.
                self.acknowledgement_handler_goto_next = True
                self.acknowledgement_handler_retry_counter = 0
                self.acknowledgement_handler_expecting = False
                pass


        # we have see a response!:
        if  (self.packet_recieved == True):
            #self.acknowledgement_handler_start = 0  # to flag that we should stop repeating the outbound packet..
            self.acknowledgement_handler_goto_next = True
            self.acknowledgement_handler_retry_counter = 0

            #print "toom"
 
            self.packet_recieved = False

            if self.acknowledgement_handler_expecting == True:
                print "\t ------> GOT Message Recieved... after %s ms" % str( self.acknowledgement_handler_inprogress - self.acknowledgement_handler_start )
                self.acknowledgement_handler_expecting = False                

            pass


    def write_queued(self):

        # TODO - don't queue an identical message more than once...

        if self.writeq == None:
            self.writeq = SimpleQueue()


        if self.alive:  # don't try to write if we already *know* the serial port isn't valid
            #try: 

                if self.acknowledgement_handler_goto_next == True:
                    #print "check queue"+str(self.writeq.is_empty())
                    if not self.writeq.is_empty():   # not empty

                        data = self.writeq.pop()

                        print "actual write: "+str(make_bytes_readable_hex(data))   # debug only
                        self.ser.write(data)
                        self.acknowledgement_handler_goto_next = False  # disallow pulling more from the queue till we have procesed this fully ( with retries etc ) 
                        self.acknowledgement_handler_data = data
                        self.acknowledgement_handler_start = current_milli_time()
                        self.acknowledgement_handler_done = current_milli_time()+100 # giveup after this many ms.
                        self.acknowledgement_handler_retry_counter = 1   # start activity now.
                        self.acknowledgement_handler_expecting = True
                        print "     -----> WAITING FOR Message Recieved... for 100ms max"

            #except:
            #    print("ERROR: unable to write to busted com port, sorry")
            #    self.alive = False   # also don't try to write if we discover as we are doing it, that the serial port is invalid, in that case, we close it and go into re-open loop elsewhere
        else:
            print("ERROR: unable to write to closed com port, sorry")


    # a direct-to-serial write  - ASYNC, we need to let self.ser.read(1) continue to process incoming things while we do this...
    def writeSerial(self, priority, data):

        if self.writeq == None:
            self.writeq = SimpleQueue()

        if priority == 0:
            self.writeq.highpush(data)
        else:
            self.writeq.push(data)


# just used internally to SerialReaderWriter so it doesn't need to be thread safe. 
class SimpleQueue:
    """A Mostly First-In-First-Out data structure....with tweaks"""
    def __init__(self):
        self.in_stack = []
        #self.out_stack = []

    # high priority push, adds it to the *front* of the queue ( the end of the list ), 
    # ... violating the usual fifo.
    def highpush(self, obj):  
        return push(obj,highpush=True)

    def already(self,obj):
        found = 0
        try:
            found=self.in_stack.index(obj)
        except ValueError:
            return False
        if (found > 0 ): 
            return True # if we found an identical packet already in the outgoing queue, don't re-add it...
        return False

    def push(self, obj,high=False):

        if self.already(obj):  # dissalow dupes
            return

        if obj.startswith("02 02 04 01"):
            print "found a request to change network state - clearing the way ( the queue) !"
            high=True
            #self.in_stack = []
            #self.out_stack = []

        if obj.startswith("02 02 0E 00"):
            print "found a complete network reset request - clearing the way ( the queue) !"
            high=True
            #self.in_stack = []
            #self.out_stack = []
        
        # usual behaviour:
        if high==False:
            self.in_stack.insert(0,obj)   # new items added at start of list, old items taken from the end.
        else:
            self.in_stack.append(obj) # high priority push, adds it to the *front* of the queue ( the end of the list )

        # TODO? if we push a new network state ( starts with 02 02 04 01 ), then drop all earlier queued msgs with that prefix and push the new one instead...
        #print "QueuePush:"+self.display()

    def display(self):
        r = "queue:\n"
        for x in self.in_stack:
            r = r+str(make_bytes_readable_hex(x))+"\n"
        #r = r+"out:\n"
        #for x in self.out_stack:
        #    r = r+str(make_bytes_readable_hex(x))+"\n"
        return r

    def pop(self):
        #if not self.out_stack:
        #    self.in_stack.reverse()
        #    self.out_stack = self.in_stack
        #    self.in_stack = []
        #print "QueuePop:"+self.display()
        #return self.out_stack.pop()
        return self.in_stack.pop()

    def is_empty(self):
        if len(self.in_stack) == 0:# and len(self.out_stack) == 0:
            return True
        return False

if __name__ == '__main__':
    print("starting LOW serial reader-writer as standalone... thx.")
    low_serial_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()   # we send data TO the serial input device
    low_serial_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()  # get from

    gDEVICES = {}  # when we r testing we don't share this. 

    # now we try to attach to the serial device, if we can. 
    lowgw = SerialReaderWriter( low_serial_input_queue, low_serial_output_queue , gDEVICES)   # the comport is selected in __init__ in the SerialReaderWriter.py file. 
    lowgw.daemon = True
    lowgw.start()
    time.sleep(1); # seems to need at least a second here. - windowsism? 
    lowgw.expecting_ack = False


    secs = 0;
    while True:
        secs = secs+1
        time.sleep(1)
        #print "serial reader-writer is idling"

