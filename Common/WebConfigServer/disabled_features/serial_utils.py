import serial
import binascii
# use like this:
#from serial_utils import  make_bytes_readable_hex,serial_send,serial_receive, un_pretty

# the opposite of make_bytes_readable_hex is:
def un_pretty(tmp):
     return bytearray.fromhex(tmp)  # tmp comes in as is something like "02 02 0C 00 F3 03" and leaves as byte-data.
#def pretty(tmp):
#return make_bytes_readable_hex(tmp)

# the opposite of make_MAC_readable_hex is:
def un_pretty_MAC(tmp):
     tmp.replace(":"," ")    # ff:ee:dd:cc:bb:aa -> ff ee dd cc bb aa
     return bytearray.fromhex(tmp)  # tmp comes in as is something like "02 02 0C 00 F3 03" and leaves as byte-data.


#print make_bytes_readable_hex("test")
def make_bytes_readable_hex(tmp):
    hex = str(binascii.hexlify(tmp))
    formatted_hex = ' '.join(hex[i:i+2] for i in range(0, len(hex), 2))
    return formatted_hex

def make_MAC_readable_hex(tmp):
    hex = str(binascii.hexlify(tmp))
    formatted_hex = ':'.join(hex[i:i+2] for i in range(0, len(hex), 2))
    return formatted_hex

#def serial_send(ser,tmp):
#   print("SEND>> "+make_bytes_readable_hex(tmp)+"\n")
#   ser.write(tmp)
#   pass

def serial_receive(ser):
    bytesToRead = ser.inWaiting()
    if bytesToRead == 0 : 
                    return
    data = ser.read(bytesToRead)
    print("RECV<< "+make_bytes_readable_hex(data)+"\n")
    return data
