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
from file_utils import change_leds
from SimplePriorityQueue import SimplePriorityQueue


# copyright David "Buzz" Bussenschutt 2015, all rights reserved.
#some inspiration from http://fabacademy.org/archives/2015/doc/WebSocketConsole.html

last_check_time10 = 0
last_check_time5 = 0

# convenience function. current_milli_time()
current_milli_time = lambda: int(round(time.time() * 1000))


class SerialPacketHandler(Process):

    def __init__(self,  input_queue, output_queue, gDEVICES = {}):
        Process.__init__(self)
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.alive = False   # assume we are NOT connected to start with, so it forces a re-connect.
        self.expecting_ack = False
        #print("expecting ack = False")
        self.smalldelay = 0.1
        self.gDEVICES =  gDEVICES  # device list, including the record of assigned NodeIDs and which MAC each is assigned to, and it's latest timestamp info, and more, in a hash
        self.lastresettimestamp = 0  # time of most recent gateway reset DT_Alive
        self.device_list_start = None  # internal timer for knowing how often to send DEVICELIST2 messages see device_list_start
        self.device_list_prev = None   #
        self.startup_time =  time.time()   # this records the bootup time.... so after 30 seconds of bootup we drop to low power mode. 
        self.highstart = 0  # internal use.
        self.lowstart = 0
        self.midpacket = 0  # we set this to 1 while we are in the moddile of reading a packet....
        self.writeq = None
        #self.readq = None
        self.STX=b'\02';  # start of packet x2
        self.ETX=b'\03';   # end of packet x1
        self.NextNodeID = 1   # THIS IS AN INT in BASE 10! ... in the gDEVICES we store the list of used Network NodeIDs, this is to make handing those out easier. 
        self.busy = True  # assume we are busy at the start. , this is just a CPU cycle saver
        self.busycount = 0
        change_leds(0,None,None)  # red disable on startup, if not already



    def run(self):
        global last_check_time10
        global last_check_time5
        sys.stdout = CustomPrint(sys.stdout,"SERIAL_PACKET> ","WebConfigServer_serialpacket.log")
        proc_name = self.name
        pid = os.getpid()
        setproctitle.setproctitle("APSync SerialPacket")
        print("Starting: %s process with PID: %d " % (proc_name, pid))

        print(" waiting 5 secs for debugger to be attached manually")
        #time.sleep(5)
        backoff = 1

        # also implemented as gateway()
        print "sending initial gateway init packet"
        self.writeSerial(1,un_pretty("02 02 0C 00 F3 03"))

        # also send initial packt to put the serial into "HighAlert" mode for a bit...


        # tmp vars for holding the incompletely parsed packet that we are working on..
        currentpacketlengthlsb = 0
        currentpacketcommand = 0
        currentpacketdataamount = 0
        MAXSERIALPACKETLENGTH = 30

        last_second = 0

        while (True ) : 

            now = int(time.time())  # time in exact seconds ( needs to be rounded to secs, or below tests will fail)

            # if we aren't doing much . we can afford to use less CPU. 
            if self.busy == False:
                time.sleep(0.1)

            # if we've had ZERO messages in the last second, we reset the "busy" marker to say not busy.   
            if now != last_second:
                if (self.busy == True) and (self.busycount == 0):
                    self.busy = False
                self.busycount = 0
                last_second = now
              
            # handle regular outgoing
            # call regular time function to see if it needs to go off yet
            self.send_device_list(now)   # it's done every 5 seconds or so.

            # handle irregular outgoing 
            self.other_periodic_events(now)   # 10 sec loop, and 5 secs after startup, and 1 minute after startup.

            # handle incoming packets
            if not self.input_queue.empty():
                self.handle_data_from_incoming_queue() # as there is data in the queue to be handled. 
                self.busycount += 1 # just used to decide if we are busy or not.
                self.busy = True    # if we are getting any msg at all, assume it will have friends and we'll be busy
      

    # starting with a completed in-coming response packet, we identify and respond to ( with outgoing backet/s etc as -required).
    def handle_responses(self,response):


            #print "response:"+repr(response)
            #print "decoded:"+repr(response.decode('utf-8'))

            # table 2 in spec says we need to handle these "outgoing the gateway" types: 
            #0x01	DT_AnsVersion	Answer version string	variable     ( comes as a response to a DT_ReqVersion )
            #0x03	DT_AnsNodeData	Retrieve information for a network node. Refer to table 3.	variable	( which we answer with DT_AckDevState  )   
            #0x05	DT_ReqNetID	Request a network ID for a given MAC	 ( which we answer with a DT_AnsNetID )    
            #0x07	DT_Ack	Command acknowledgement	0	   
            #0x08	DT_Nack	Command refusal	0	   
            #0x0D	DT_DeviceAlive	Sent every time the device is powered-on or resets	0	 ( which we essentially answer with a DT_SetGateway packet )
            #0x12   DT_MessageRecieved in the 5th August 2012 spec. ( send as synchronous acknowledgement for confirming receipt every other packet we send ) 

            # first unpack the header, so we know how big the data segment is
            try:
              stx1,stx2,command,lengthlsb =      unpack('BBBB', response[0:4])   #  < means little endian
            except:
              print("weird arse packet header arrived, sorry, can't handle it"+make_bytes_readable_hex(response[0:4]))
              return
            # determine valid size of packet from fixed list...
            expectedsize = self.payloadsize_from_packettype(command)

            #actual packet size that came in is: 2 byte stx1&stx2 header + 1 byte packet type ie "command" + lengthlsb bytes + 1 checksum byte + end-of=packet byte ( etx ) 
            actual_payload = response[4:4+lengthlsb]
            checksum_byte = response[4+lengthlsb:4+lengthlsb+1]
            etx_byte =  response[4+lengthlsb+1:4+lengthlsb+2]

            willreturn = 0
            # deal with non-normal packets.
            if( expectedsize == -1)  or (etx_byte != self.ETX) : 
                print("ERROR, didnt handle expectedsize or etx of a packet ( len %d), ignoring, sorry" % lengthlsb )
                willreturn = 1

            # deal with variable length of packet types 1 & 3  ( where expectedsize = 99 )

            # check if it's a known and std packet length.? 
            if (lengthlsb > 0) and (expectedsize != -1) and (lengthlsb != expectedsize)  and (expectedsize != 99) : 
                print("ERROR, defined packet len(%d) differed from actual packet len(%d), ignoring, sorry" % (expectedsize,lengthlsb))
                willreturn = 1

            # displays us a pretty line on console for the incoming packet...
            #command = data[2];
            type = self.packetname(command);
            print("PRE<<< "+type+" < "+make_bytes_readable_hex(response))   

            # put RED in the LEDs if not already there
            change_leds(1,None,None)  # red disable on startup, if not already


            # exclude this one as it's noisy, log the rest...
            if type != 'AnsNodeData':
                #  browser / logger all incoming packets irrespective of type and what we do after to respond to it...
                l = {}
                l['SERIAL'] =  {}
                l['SERIAL']['RECV<<'] = type
                self.output_queue.put(1,json_wrap_with_target(l,'logging'))

            #we've logged the problem with the bad packet, and with the above "PRE" done our duty 
            #to send the complete packet to the logging system, so now we just return, as we can't actually parse that packet.
            if willreturn == 1:
                return

           ## reminder 
           # if expectedsize == 0:
           # if expectedsize == 99:   # variable length packets get a reported "max" expectedsize of 99  ( packets types 2 and 4 ) 
           # if expectedsize == -1:   # otherwise entirely unknown packets get a reported expectedsize of -1



            if type == 'Nack':   #0x01
                # we do nothing with this type right now other than display/log it above. 
                pass

            if type == 'Ack':      #0x07
                if self.expecting_ack == True:
                    #print("expecting ack = False - flipped from True")
                    self.expecting_ack = False;
                #else:
                #    # we weren't expecting an ack, but lets send one anyway..
                #    print("acknowledging out-of-order ACK")
                #    packet = self.ack()
                #    self.print_pretty_sent_packet(un_pretty(packet))
                #    #self.input_queue.put(1,packet);
                #    # or more directly: 
                #    self.writeSerial(1,un_pretty(packet))


            if type == 'ReqNetID':   #0x05 
                    print("we got a network ID request.")
                    MAC = response[4:10]
                    print("client has a MAC of "+make_MAC_readable_hex(MAC)) # for human

                    # we always respond to network requests as we may have rebooted a serial node, and need to re-do it.
                    print  "Responding to NodeID request....\n"
                        
                    # determine NID - either it's already been assigned for this MAC and we have an existing one, or we pick the next-available unused.
                    NodeID = ""
                    devices = self.gDEVICES.copy() # temp copy of thread shared resource
                    if make_MAC_readable_hex(MAC) in devices  :  # it's a known existing device..
                        #(timestamp, NodeID ) =  devices[make_MAC_readable_hex(MAC)]    # NodeID is a string, timestamp is a long int
                        tmpd =  devices[make_MAC_readable_hex(MAC)]
                        timestamp = tmpd['LastDeviceSeenDateTime']
                        NodeID = tmpd['NodeID'] # use the nodeID we want them to have, not necessarily the one they currently have.
                        print "(NodeID, timestamp)"+NodeID+" "+str(timestamp)#" "+type(NodeID)+" "+type(timestamp)
                        #if type(NodeID) != 'str':
                        #NodeID = NodeID.zfill(2) 
                        print "Found existing NodeID: "+NodeID
                    else:                        # it's a new one
                        x = hex(self.NextNodeID)[2:] #  51 -> 0x33 -> 33
                        NodeID = x.zfill(2)     # takes the number and stringifies it to two decimal places with zero-fill ( to be compatable with assemble_node_id_reply etc ) 
                        if self.NextNodeID > 100: 
                            print "NodeID would exeed decimal 100, failed to assign a HIGHER NodeID.... searching for lower one.... "
                            NodeID = self.find_free_node_id(devices)
                        else: 
                            print "Issued New NodeID: "+NodeID
                            self.NextNodeID = self.NextNodeID + 1

                    #irrespective of if known previously or not.... now we respond to the packet and.. 
                    packet = self.assemble_node_id_reply(make_bytes_readable_hex(MAC),NodeID)
                    self.print_pretty_sent_packet(un_pretty(packet)) # kinda weird to un_pretty it, just to pretty-print it..but whatever.
                    self.writeSerial(1,un_pretty(packet))

                    # ...we record it, and also logs it to the browser. etc
                    self.register_device(make_MAC_readable_hex(MAC),NodeID,int(time.time()))  # other params are unknown at this time, so we default them  


                    #print "Serial Nodes Connected (right now): "+str(self.gDEVICES)


            if type == 'AnsVersion':   #0x01
                # TODO we do nothing with this type right now other than display/log it above. 
                pass

            if type == 'DeviceAlive':  # we need to re-do the gateway initialisation each time the device reset/s, and this tells us that.
                #future enhancement - if we get more than 2 of these in a 5 second period, we are clearly in a Serial Device reset loop ( low or no battery? ) , so DONT keep ACKing it, but report, LOG, and Fail ourselves. 
                #now = time.time()
                #if now - self.lastresettimestamp  > 30:   # we might just limit ourselves to one reset every 30 secs...? 
                reinitpacket = self.gateway()
                self.print_pretty_sent_packet(un_pretty(reinitpacket))
                #self.expecting_ack = True;
                self.writeSerial(1,un_pretty(reinitpacket))
                self.lastresettimestamp = time.time()
               # else : 
                #    self.lastresettimestamp = time.time()
                #    pass

            #DT_AnsNodeData can be a bit convoluted..  in short:
            # if DT_AnsNodeData comes from a serial node when it's changed State.
            # the message gets propogated to PORTAL as a ['DeviceChange'] message
            # PORTAL responds to that message with "status":"OK" ( and "AcknowledgedDeviceStatus" = 2 or 4 ) , and 
            # when that response is finally passed back to the SerialPacketHandler module,  
            #especially when DeviceStatus is 2 or 4 , a AckDevState packet is sent back to the node, confirming it.

            if type == 'AnsNodeData':   #0x03
                    #print "actual_payload:"+repr(actual_payload)


                    # see 20160705 version of the spec for these offsets  "DT_AnsNodeData packet data structure", table 3.
                    # earlier versions were different.
                    myNodeID = actual_payload[0:1]      # leave it as a str
                    HumanReadableNodeID = make_bytes_readable_hex(myNodeID) # but expand it two two places, etc.
                    # for compat reasons, we also call it NodeID, they are the same thing:
                    NodeID = HumanReadableNodeID
                    Battery =  actual_payload[1:2] # one byte, data in decivolts.
                    HumanReadableBatteryLevel = float(ord(Battery))/float(10) # a float, not a str
                    # TIP in python:  [2:4] mean two bytes 2 and 3
                    Temperature = actual_payload[2:3] # one byte, degrees Celcius
                    #print("RawTemperature = "+repr(Temperature))                      
                    HumanReadableTemperature = ord(actual_payload[2:3])     # an int, not a str

                    status_firmware_byte = actual_payload[3:4]
                    upper5 = ord(status_firmware_byte) & 0b11111000
                    lower3 = ord(status_firmware_byte) & 0b00000111
                    #upper3 = ord(status_firmware_byte) & 0b11100000
                    #lower5 = ord(status_firmware_byte) & 0b00011111
                    HumanReadableFirmwareVersion  = upper5 >> 3 #  upper x bits, but shifted to the right by x
                    DeviceStatus = lower3   # lower x bits of one byte

                    # bounds limit it in case of error. 
                    if HumanReadableFirmwareVersion > 31 or HumanReadableFirmwareVersion < 1:
                        HumanReadableFirmwareVersion = 0.9

                    #print "TEST TEST TEST upper5: %d  lower3: %d" % (upper5, lower3 ) 
                    #print "TEST TEST TEST binary5: %s binary3: %s" % (str(bin(upper5)), str(bin(lower3)) ) 
                    #print "TEST TEST TEST ver: %d  status: %d" % (HumanReadableFirmwareVersion ,DeviceStatus ) 

                    SerialAddress = str(actual_payload[7:9])  # two bytes 7,8
                    SerialChannel = str(actual_payload[9])  # one byte 9
                    NetworkAddress = str(actual_payload[7:9])   # alternate 3 byte form of the above three is this
                    HumanReadableNetworkAddress =  make_MAC_readable_hex(NetworkAddress)
                    MACAddress =      str(actual_payload[10:16])  # six bytes 10,11,12,13,14,15
                    HumanReadableMAC =  make_MAC_readable_hex(MACAddress)

                    # enable for more debug..
                    if False:
                        print("NodeID = "+HumanReadableNodeID)
                        print("Battery = "+str(HumanReadableBatteryLevel))   
                        print("Temperature = "+str(HumanReadableTemperature))  
                        print("DeviceStatus = "+ str(DeviceStatus)),
                        print("NetworkAddress = "+ HumanReadableNetworkAddress)
                        print("MACAddress = "+HumanReadableMAC)


                    #NOTE  - we do NOT acknowledge this packet immediately, in the SerialRW module, it needs to be acknowledged later, at the PORTAL level, then come back to us.
                    #so this code is disabled here, and we instead respond after getting a AcknowledgedDeviceStatus reply ( to our DeviceChange msg )  from PORTAL. ( see json sample files ) 
                    if False: 
                        # to Acknowledge the DT_AnsNodeData, you need to use a DT_AckDevState  ( not in original spec, only in 20160705 or later like this) 
                        # and the key part is that the first byte is the Node ID, and the second byte is the State
                        
                        packet = self.assemble_AckDevState(HumanReadableNodeID,make_bytes_readable_hex(chr(DeviceStatus)))
                        self.print_pretty_sent_packet(un_pretty(packet))
                        #self.expecting_ack = True;
                        self.writeSerial(1,un_pretty(packet))   


                    devices = self.gDEVICES.copy();  # don't mess with the multi-process proxy object, use a copy, it's safer.


                    # quick duplicate check and lookup.
                    d = None
                    ExistingNodeID = None
                    NewNodeID = None
                    worth_sending_update = True
                    if  HumanReadableMAC in devices:
                        d =  self.gDEVICES[HumanReadableMAC]
                        timestamp = d['LastDeviceSeenDateTime']
                        ExistingNodeID = d['NodeID']
                        print "Found existing NodeID: "+NodeID+"("+ExistingNodeID+") with MAC: "+HumanReadableMAC

                        # a device we know about comes to us claiming it's one ID, when we think it should be already another...
                        if ExistingNodeID != HumanReadableNodeID:
                            print "Found continued conflict for a NodeID: "+NodeID+" with MAC: "+HumanReadableMAC 
                            # send packet to node to tell them to change ID
                            packet = self.assemble_node_id_reply(make_bytes_readable_hex(MACAddress),ExistingNodeID); # for network
                            self.print_pretty_sent_packet(un_pretty(packet)) # kinda weird to un_pretty it, just to pretty-print it..but whatever.
                            self.writeSerial(1,un_pretty(packet))

                        # if we've NOT had this node updated to PORTAL in the last 5 minutes, send an update, otherwise 
                        # we'll manage this directly here...
                        last_seen = int(time.time()) - devices[HumanReadableMAC]['LastDeviceSeenDateTime']
                        if (DeviceStatus == devices[HumanReadableMAC]['NewDeviceStatus']) and  ( last_seen <=  300 ) :
                            worth_sending_update = False

                    else:
                        #in this case NodeID = HumanReadableNodeID
                        print "Found NEW NodeID: "+NodeID+" with MAC: "+HumanReadableMAC
                        # since we've not seen the NodeID, if we are going to allow it, we'd better bump our Assignment list up to at least that high:
                        if self.NextNodeID <= int(NodeID,16):
                            self.NextNodeID = int(NodeID,16)+1
                        ## did we find this node has an ID that is already used by another with different MAC address?  
                         # if so, tell it to shift to a different/ new NodeID
                        
                        for tmpdev in devices:
                            if (devices[tmpdev]['NodeID'] == HumanReadableNodeID ) and ( tmpdev != HumanReadableMAC):
                                print "Found conflict for a NodeID: "+NodeID+" with MAC: "+tmpdev+" and with MAC: "+HumanReadableMAC 
                                if self.NextNodeID > 100: 
                                    print "NodeID would exeed 100, failed to assign a HIGHER NodeID.... searching for lower one.... "
                                    NodeID = self.find_free_node_id(devices)
                                else: 
                                    # assign new NID we pick the next-available unused.
                                    x = hex(self.NextNodeID)[2:] 
                                    NewNodeID = x.zfill(2)     # takes the number and stringifies it to two decimal places with zero-fill ( to be compatable with assemble_node_id_reply etc ) 
                                    print "Issued New NodeID: "+NewNodeID+" to  MAC: "+HumanReadableMAC 
                                    self.NextNodeID = self.NextNodeID + 1
                                    # send packet to node to tell them to change ID
                                    packet = self.assemble_node_id_reply(make_bytes_readable_hex(MACAddress),NewNodeID); # for network
                                    self.print_pretty_sent_packet(un_pretty(packet)) # kinda weird to un_pretty it, just to pretty-print it..but whatever.
                                    self.writeSerial(1,un_pretty(packet))


                    # above, we have validate from the new Node if it's NodeId is already used by someone else in our records... if so we reassign its node id:
                    if NewNodeID != None:
                        NodeID = NewNodeID
                    # above, we have validate from the new Node if it's NodeId is already used by someone else in our records... if so we reassign its node id:
                    if ExistingNodeID != None:
                        NodeID = ExistingNodeID

                    
                    # records it, and also logs it to the browser. etc as DEVICELIST 
                    self.register_device(HumanReadableMAC,NodeID,int(time.time()), HumanReadableBatteryLevel,HumanReadableTemperature,1,HumanReadableFirmwareVersion,DeviceStatus,'','')  


                    devices = self.gDEVICES.copy() # read from copy, not proxy object, its safer
                    #print "Serial Nodes Connected (right now): "+str(devices)


                    # only do it if more than 5 mins have elapsed, or if the state has changed....
                    if ( worth_sending_update ) :

                        # Push the NODE STATUS PACKET OUT IN JSON FORMAT TO PORTAL.
                        emptymessage = '''{ "DeviceChange": { }  }'''  # start with string format.

                        devicechangejson = json.loads(emptymessage)    # turn it into python format
                        devicechangejson['DeviceChange'][HumanReadableMAC] = {}   # extend the data in the python-formatted variable
                        devicechangejson['DeviceChange'][HumanReadableMAC]['BatteryLevel'] = HumanReadableBatteryLevel
                        devicechangejson['DeviceChange'][HumanReadableMAC]['Temperature'] = HumanReadableTemperature
                        devicechangejson['DeviceChange'][HumanReadableMAC]['RSSI'] = 1.0
                        devicechangejson['DeviceChange'][HumanReadableMAC]['FirmwareVersion'] = str(HumanReadableFirmwareVersion)  # eg '1', or '32'
                        devicechangejson['DeviceChange'][HumanReadableMAC]['NewDeviceStatus'] = DeviceStatus
                        devicechangejson['DeviceChange'][HumanReadableMAC]['LastDeviceSeenDateTime'] = int(time.time())
                        devicechangejson['DeviceChange'][HumanReadableMAC]['NodeID'] = make_bytes_readable_hex(myNodeID)
                        print repr(devicechangejson)

                        m = devicechangejson  # this keeps us only having one sub-level of 'DeviceChange' or 'DEVICECHANGE' in the JSON

                        # queue the JSON string in the outgoing queue for elsewhere to use.
                        self.output_queue.put(1,json_wrap_with_target(m,'portalclient'))  # interesting, this one ALSO logs the outgoing result TOPORTAL, so no need to do two of these lines.
                        # the "response" to this is handled elsewhere 

                    else:  # recently seen device, we can handle this locally to PORTAL is not flooded to retries..
                        print "LOCAL RECENT DEVICE DOING RETRY"
                        packet = self.assemble_AckDevState(HumanReadableNodeID,make_bytes_readable_hex(chr(DeviceStatus)))
                        self.print_pretty_sent_packet(un_pretty(packet))
                        #self.expecting_ack = True;
                        self.writeSerial(1,un_pretty(packet))   


            if type == 'Nack':   #0x08
                # future enhancement -  handle 'Nack' packet properly.
                pass


            time.sleep(self.smalldelay);

    def handle_data_from_incoming_queue(self):
            #if not self.input_queue.empty():
            # look for incoming request
            qdata = ''
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
            if ('response' in json_data):
                # with "response" data we do nothing right now.
                return

            # handle internally initiated types from serialrw module for timing and packet routing etc..
            #if ('self.alive' in json_data):
            #    self.alive = json_data['self.alive']  # simply way to keep the two serial modules in-sync

            if ('incomingserialpacket' in json_data):   
                    self.handle_responses(un_pretty(json_data['incomingserialpacket']))
                    

            # or... Is this a legit server-initiated type? 
            # outgoing PORTAL packets...

            if ('Heartbeat' in json_data) or ('HighAlert' in json_data):
                print("\HIGHALERT/HEARTBEAT STARTING !!! \n")
                packet = self.heartbeat()
                self.print_pretty_sent_packet(un_pretty(packet))
                #self.expecting_ack = True;
                self.writeSerial(0,un_pretty(packet)) # priority 0 ! 

            if ('NetworkReset' in json_data):
                print("\NetworkReset STARTING !!! \n")
                packet = self.network_reset()
                self.print_pretty_sent_packet(un_pretty(packet))
                #self.expecting_ack = True;
                self.writeSerial(0,un_pretty(packet))

            if ('AllClear' in json_data):
                #src = json_data['AllClear']
                print("\nSTANDBY STARTING! !!! \n")
                packet = self.standby()
                self.print_pretty_sent_packet(un_pretty(packet))
                #self.expecting_ack = True;
                self.writeSerial(0,un_pretty(packet))
                    # and allow the PORTAL cliebnt module to  respond with the appropriate list os MACs that were put in that mode.    


            # this is used by the PORTAL to cycle the specific requested Node in the serial through each of it's 4 Modes ( ie different colours )  that it would usually get to through being Swiped.
            if ('ChangeStatus' in json_data):   # this is where we respond to the ChangeStatus reqest from PORTAL 

                # itterate over each of the requested MAC addresses in the incoming JSON from PORTAL:            
                for MACchange in json_data['ChangeStatus']:  # MACchange is already human-readable in gDEVICES, so doesn't need make_bytes_readable_hex()
                    #MACchange is a human-readable 
                    newstatus = str(json_data['ChangeStatus'][MACchange])
                                
                    newstatus_string = newstatus.zfill(2); 
                    devices = self.gDEVICES.copy()   # shallow temp copy for iterating.
                    if MACchange in devices:   # if we actually know about this MAC:
                        print "Changing MAC in ChangeStatus request("+MACchange+") with newstatus of ("+newstatus_string+")"
                        #  determine the NodeID from the MAC we were given
                        tmpd =  devices[MACchange]
                        timestamp = tmpd['LastDeviceSeenDateTime']
                        NodeID = tmpd['NodeID']
                        packet = self.assemble_SetDevState_reply(NodeID,newstatus_string)
                        self.print_pretty_sent_packet(un_pretty(packet))
                        #self.expecting_ack = True;
                        self.writeSerial(1,un_pretty(packet))

                    # we assemble the return packet in the portal client...? 

                    else:
                        print "UNKNOWN MAC in ChangeStatus request("+MACchange+") with newstatus of ("+newstatus_string+")"
                         

            # this is the daily ( or periodic etc ) request that bundles up all the known devices and sends them to the cloud.
            if ('DeviceUpdateRequest' in json_data):  # the outgoing data from this to PORTAL is known as "DeviceUpdate", this is where we make it...

                # Typically before we call this, we want to wakeup all the nodes with the Heartbeat command and afterward after it is done, we'll sleep them again. 
                # as it can take some time we don't  do this here, we'll instead do it through CRON, and the highalert.json and highalert.bat ( or equiv on linux )


                #print "Serial Nodes Connected : "+str(self.gDEVICES)

                #Push the NODE STATUS PACKET OUT IN JSON FORMAT TO PORTAL.
                emptymessage = '''{ "DeviceUpdate": { }  }'''  # start with string format.
                deviceupdatejson = json.loads(emptymessage)    # turn it into python format

                devices =  self.gDEVICES.copy() 

                deviceupdatejson['DeviceUpdate'] = devices   #   we drop the entire list in as-is, for now. 

                m = deviceupdatejson  # 

                # queue the JSON string in the outgoing queue for elsewhere to use.
                #self.output_queue.put(1,json_wrap_with_target(m,'logging'))
                self.output_queue.put(1,json_wrap_with_target(m,'portalclient'))  # interesting, this one ALSO logs the outgoing result TOPORTAL as a duplicate to the above, so we don't need it really.

                pass

            if ('AcknowledgedDeviceStatus' in json_data):

                for mac in json_data['AcknowledgedDeviceStatus']:

                    tmp_stat = json_data['AcknowledgedDeviceStatus'][mac]['NewDeviceStatus']
                    tmp_nid = json_data['AcknowledgedDeviceStatus'][mac]['NodeID']
            
                    # to Acknowledge the DT_AnsNodeData, you need to use a DT_AckDevState  ( not correct in original spec, only in 20160705 or later like this) 
                    # and the key part is that the first byte is the Node ID, and the second byte is the State
                    #packet = self.assemble_AckDevState(HumanReadableNodeID,make_bytes_readable_hex(chr(DeviceStatus)))
                    packet = self.assemble_AckDevState(tmp_nid,make_bytes_readable_hex(chr(tmp_stat)))
                    self.print_pretty_sent_packet(un_pretty(packet))
                    #self.expecting_ack = True;
                    self.writeSerial(1,un_pretty(packet))



    def other_periodic_events(self,now):
                global last_check_time5
                global last_check_time10

                if now > last_check_time10+10: # we post idle message at least every 10 secs
                    last_check_time10 = now
                    print "serialpacket loop is idling"
                    ## ping central thread to tell them we are still here...
                    queue_ping(self.output_queue,'packetgw')

                if now > last_check_time5+5: # we post idle message at least every 5 secs
                    last_check_time5 = now
                    # give the serial a minimum of traffic. ( 1 packet per 5 secs ): 
                    packet = self.keepalive()  # 
                    self.print_pretty_sent_packet(un_pretty(packet))
                    self.writeSerial(1,un_pretty(packet))

                # after being up for 5 secs, we go to HIGH power mode. 
                if  (self.highstart == 0) and (now > self.startup_time + 5):
                    print("\HIGHALERT STARTING! ( 5 seconds after boot ) \n")
                    packet = self.heartbeat()  # invisible , but serial is on.
                    self.print_pretty_sent_packet(un_pretty(packet))
                    self.writeSerial(1,un_pretty(packet))
                    self.highstart=1

                # after being up for 60 secs, we go to LOW power mode. 
                if   (self.lowstart == 0) and (now > self.startup_time + 60):
                    print("\nSTANDBY STARTING! ( 60 seconds after boot ) \n")
                    packet = self.standby()
                    self.print_pretty_sent_packet(un_pretty(packet))
                    self.writeSerial(1,un_pretty(packet))
                    self.lowstart=1



    def send_device_list(self,now):
        
        # send one of these lists at MOST every 5 seconds:

        if self.device_list_start == None:
            self.device_list_start=now

        end=now

        if end-self.device_list_start > 5 :
            self.device_list_start = end
    
            devices = self.gDEVICES.copy()  # a safe shallow copy of concurrent dictproxy into local dict

            # quick anti-dupe test:  is the current dict identical to the previous one, if so do nothing ?
            if self.device_list_prev != str(devices):
                self.device_list_prev = str(devices)  # save the details

                # build some JSON for sending out.
                l = {}
                l['DEVICELIST2'] = []
                for tmpdev in devices:
                    q = devices[tmpdev]
                    q['Mac'] = tmpdev
                    l['DEVICELIST2'].append(q)
            
                self.output_queue.put(1,json_wrap_with_target(l,'logging'))

        return True


    # NOTE:  the NodeID is a per-serial-device Network Node ID, and is unique to each Node. it's in stringified HEXdecimal. eg '01' ( node 1 )  or '0A' ( node 10  )
    # the MAC passed in HERE MUST be as per the output of make_MAC_readable_hex(), or read directly from a key of gDEVICES{}
    # FirmwareVersion being equal to '??' means it's not yet known, which is ok. 
    def register_device(self,MAC,NodeID='',timestamp=None, BatteryLevel = 3.6 ,  Temperature = 30 , RSSI = 1.1 , FirmwareVersion =  '??', NewDeviceStatus = 0, text1 = '', text2 = ''):

        if timestamp == None:
            timestamp = int(time.time())   # the rounded number of secs since epoch, in UTC.

        # we store these all as strings for consistency. 
        if type(NodeID) is int:
            NodeID = str(NodeID)


        # build-up the internal format to match the external JSON format, as it's convenient: ( although not compulsory )
        dev = {}
        dev['BatteryLevel'] = BatteryLevel
        dev['NodeID'] = NodeID
        dev['Temperature'] = Temperature
        dev['RSSI'] = RSSI
        dev['FirmwareVersion'] = FirmwareVersion
        dev['NewDeviceStatus'] = int(NewDeviceStatus)
        dev['LastDeviceSeenDateTime'] = int(timestamp)
        dev['text1'] = text1
        dev['text2'] = text2
        #mdev[MAC] = dev

        self.gDEVICES[MAC] = dev   #[timestamp, NodeID]

        #print "Serial Nodes Connected (right now): "+str(self.gDEVICES)



        return NodeID

    # linear search from NodeID1 upwards to 100 till we find an unused one in devices dict
    def find_free_node_id(self,devices):
        NodeID = ""
        sort_by_nodes = {}
        # build Node indexed list that gives us the NodeID as the key and the MAC as the value
        for d in devices:
            id = devices[d]['NodeID']
            sort_by_nodes[id] = d

        print repr( sort_by_nodes)   # debug it...

        # find first avail id that we aren't already using....
        for possible in range ( 1 , 100 ):
            hexpossible = hex(possible).split('x')[1].zfill(2).lower()
            if hexpossible not in sort_by_nodes:
                NodeID = hexpossible
                break

        print "NodeID = "+str(hexpossible)

        # return either the new node ID, or the empty string if we really couldn't. 
        return NodeID


    # we can't do packet types 1 & 3 here as they are variable size payloads, so we tell the *max* permitted size of those packet/s
    def payloadsize_from_packettype(self,argument): 
        switcher = {
            0: 0, # "ReqVersion",
            1: 99, # "AnsVersion",
            2: 1, #"ReqNodeData",
            3: 99, #"AnsNodeData",
            4: 1, #"SetNetworkState",
            5: 6, #"ReqNetID",
            6: 7, #"AnsNetID",
            7: 0, #"Ack",
            8: 0, #"Nack",
            9: 5, #"SetStateColour",
            10: 2, #"AckDevState",
            11: 2, #"SetDevState",
            12: 0, #"SetGateway",
            13: 0, #"DeviceAlive",
            14: 0, #"ResetDevices",  #Resets serial devices to factory default if sent
            18: 0, #"MessageReceived", internal ack for serial packetgw for other comms. 
           # 15: "Last",
        }
        return switcher.get(argument, -1)

    #packet name from number
    def packetname(self,argument):  #DType_t
        switcher = {
            0: "ReqVersion",
            1: "AnsVersion",
            2: "ReqNodeData",
            3: "AnsNodeData",
            4: "SetNetworkState",
            5: "ReqNetID",
            6: "AnsNetID",
            7: "Ack",
            8: "Nack",
            9: "SetStateColour",
            10: "AckDevState",
            11: "SetDevState",
            12: "SetGateway",
            13: "DeviceAlive",   #0x0D in spec
            14: "ResetDevices",   #0x0E in spec
            18: "MessageReceived", # 0x12 in the Spec.
            19: "SerialKeepAlive",  # 0x13 
          #  15: "Last",
        }
        return switcher.get(argument, "nothing")


    # pass thru un_pretty() b4 sending it out the serial port...
    def ack(self):
        #ack packet:
        return "02 02 07 00 F8 03"

    # pass thru un_pretty() b4 sending it out the serial port...
    def gateway(self):
        #make it a gateway
        return "02 02 0C 00 F3 03"    #\F3 = 243, \0C = 12

    # pass return data thru un_pretty() before putting it on the actual serial data line/s
    def standby(self):
        if True:
            #normally, we just go to standby
            return  "02 02 04 01 01 F9 03"  # F9 = 249
        else:
        # tweak/hack.... to allow the serial to operate WITHOUT standby for when all the node/s are fully POWERED by cables,  we can optionally do this instead:
            return self.heartbeat()  # as this turns off all the LEDS etc, but leaves the serial "up". 


    def network_reset(self):
        #  "Reset Devices" packet in 12-07-2016 spec at least.   
        return  "02 02 0E 00 F1 03"   # F1 = 241 

    def keepalive(self):
        #  "keep alive" packet added on 30th Sept 2016 by matheus/seppo.   
        return  "02 02 13 00 EC 03"   #  EC = checksum

 
   #def network_reset_dynamic(self):
   #     # packet type zero, packet length zero
   #     #return "02 02 0E 00 xx xx"
   #     assembly = "02 02 0E 00 "
   #     crc =     make_bytes_readable_hex(self.packet_checksum(assembly))   
   #     packet = assembly+" "+crc.upper()+" 03"
   #     return packet 


    def heartbeat(self):
        #goto heartbeat mode
        return  "02 02 04 01 03 F7 03"   #F7 = 247

    # ReqVersion - pass thru un_pretty() b4 sending it out the serial port...
    def requestversion(self):
        # packet type zero, packet length zero
        #return "02 02 00 00 xx xx"
        assembly = "02 02 00 00 "
        crc =     make_bytes_readable_hex(self.packet_checksum(assembly))   
        packet = assembly+" "+crc.upper()+" 03"
        return packet 

    # this takes RAW bytes and makes them pretty onscreen.
    # if they are already "prettified" b4 passing in, they will be MUNGED BADLY.
    def print_pretty_sent_packet(self,data):
        command = data[2];
        type = self.packetname(command);
        if type == "SetNetworkState":
            if data[4] ==1:
                type = type + "-standby"
            if data[4] == 3:
                 type = type + "-heartbeat"
        msg = "SEND>> "+type+" > "+make_bytes_readable_hex(data)
        print msg
        # be a bit less verbose on the browser, and exclude these two noisy ones: 
        if (type != 'AckDevState'): # and ( type != 'AnsNodeData'):
            l = {}
            l['SERIAL']=  {}
            l['SERIAL']['SEND>>'] =  type
            #this is a helpful message for user/s to see in the logging system too:
            self.output_queue.put(1,json_wrap_with_target(l,'logging'))
            #pass


    # packet type 06, payload length 07 containing:  MAC is a "pretty" 6byte bytearray, NodeID is a single "pretty" byte at teh end.
    # pass in both params as STRINGS
    # this is a 'DT_AnsNetID' packet. in the spec. 
    def assemble_node_id_reply(self,MAC,NodeID):  
        assembly = "02 02 06 07 "+MAC+" "+NodeID
        #print "assembly"+assembly
        crc =     make_bytes_readable_hex(self.packet_checksum(assembly))   
        packet = assembly+" "+crc.upper()+" 03"
        return packet

    # packet type 0x0B, payload length 2 containing:  NodeID is a single "pretty" byte, and Status is a single  "pretty" byte at the end.
    # pass in both params as STRINGS
    # DT_AckDevState  in 20160705 spec needs serial "Node Identifier"  AND a State/Status 
    def assemble_AckDevState(self,NodeID, Status):  
        assembly = "02 02 0A 02 "+NodeID+" "+Status  # 0202 is stx, 0A is type, 02 is payload len, etc
        #print "assembly"+assembly
        crc =     make_bytes_readable_hex(self.packet_checksum(assembly))
        packet = assembly+" "+crc.upper()+" 03"
        return packet

    # packet type 0x0B, payload length 02 containing:   NodeID is a single "pretty" byte, and Status is a single "pretty" byte at the end.
    # pass in both params as STRINGS
    # DT_SetDevState  in 20160705 spec needs serial "Node Identifier"  AND a State/Status ( table 5 )
    def assemble_SetDevState_reply(self,NodeID, Status):  
        assembly = "02 02 0B 02 "+NodeID+" "+Status  # 0202 is stx, 0B is type, 02 is payload len, etc
        #print "assembly"+assembly
        crc =     make_bytes_readable_hex(self.packet_checksum(assembly))
        packet = assembly+" "+crc.upper()+" 03"
        return packet

    #). The CRC is calculated by adding each byte from the Data Type field to the end of the Data field and inverting the result bit-a-bit. 
    # IMPORTANT - the packets data MUST be passed-in as pretty-formatted bytes with space separation etc.
    # and the checksum is RETURNED as an INT with a value below 255 ( for casting to a byte ), or using make_bytes_readable_hex() to pretty it.
    def packet_checksum(self,packet):
                raw = un_pretty(packet)
                # first unpack the header, so we know how big the data segment is
                stx1,stx2,command,lengthlsb =      unpack('BBBB', str(raw[0:4]))   #  < means little endian
                #actual packet size that came in is: 2 byte stx1&stx2 header + 1 byte packet type ie "command" + lengthlsb bytes + 1 checksum byte + end-of=packet byte ( etx ) 
                actual_payload = raw[4:4+lengthlsb]
                #checksum_byte = raw[4+lengthlsb:4+lengthlsb+1]
                #etx_byte =  raw[4+lengthlsb+1:4+lengthlsb+2]
                b = 0
                b = b+command
                b = b+lengthlsb
                for t in actual_payload:
                    b=b+t
                b = ~b    #  switch to the "compliment" of b, which is where all the individial bits are flipped.
                # then truncate b to the size of a byte, and return just the lower 8 bits.
                high,low = [int(b >> i & 0xff) for i in (8,0)]
                return chr(low)



    def close(self):
        self.alive = False


    # a indirect-to-serial write via the realtime serial modiule...
    def writeSerial(self, priority, data):

        p = {}
        p['writepacket'] = make_bytes_readable_hex(data)  #this can be un_pretty()'d later.
        p['priority'] = str(priority) # remember it
        self.output_queue.put(priority,json_wrap_with_target(p,'serialrw'))
        
 

if __name__ == '__main__':
    print("starting serial packet-handler as standalone... thx.")
    serialpacket_input_queue = SimplePriorityQueue(2) #multiprocessing.Queue()   # we send data TO the serial input device
    serialpacket_output_queue = SimplePriorityQueue(2) #multiprocessing.Queue()  # get from

    gDEVICES = {}  # when we r testing we don't share this. 

    # now we try to attach to the serial device, if we can. 
    packetgw = SerialPacketHandler( serialpacket_input_queue, serialpacket_output_queue , gDEVICES)   # the comport is selected in __init__ in the SerialReaderWriter.py file. 
    packetgw.daemon = True
    packetgw.start()
    time.sleep(1); # seems to need at least a second here. - windowsism? 
    #packetgw.expecting_ack = False


    #packet = packetgw.gateway()
    #packetgw.print_pretty_sent_packet(un_pretty(packet))
    #packetgw.expecting_ack = True;
    #print("expecting ack = True")
    #lowserial_input_queue.put(1,un_pretty(packet))

    secs = 0;
    while True:
        secs = secs+1
        time.sleep(1)
        print "serial packet handler is idling"

        if secs > 10:
            secs = 1
            

            print("\nSTANDBY STARTING! ( 10 seconds in ) \n")
            packet = packetgw.standby()
            packetgw.print_pretty_sent_packet(un_pretty(packet))
            #packetgw.expecting_ack = True;
            print("expecting ack = True")
            packetgw.writeSerial(0,un_pretty(packet))

            x = 0
            while x < 15: 
              x=x+1
              time.sleep(1)

            print("\NETWORK RESET STARTING! \n")
            packet = packetgw.network_reset()
            packetgw.print_pretty_sent_packet(un_pretty(packet))
            #packetgw.expecting_ack = True;
            print("expecting ack = True")
            packetgw.writeSerial(0,un_pretty(packet))
