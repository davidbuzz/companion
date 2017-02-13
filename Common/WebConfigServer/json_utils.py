import json
import time
import os
import multiprocessing
import sys
from file_utils import  file_put_contents

# take arbitrary json ( or other text ) , and wrap it in a higher JSON layer with a "label" which is the target/destination
# returned data is the text-ified JSON after the wrap.
def json_wrap_with_target(data, target = 'logging', priority = 1):

    try:   # in case it's not actually JSON 
        #json_data = json.loads(data)
        wrapper = {}
        wrapper['_target'] =   target
        wrapper['_priority'] =   priority
        wrapper['data'] =   data
        cleaned = json.dumps(wrapper,indent=2,sort_keys=True)    
        return cleaned
    except: 
        print "CRITICAL json_wrap_with_target FAILED: "+str(data)
        return False
   

# take arbitrary "wrapped" json ( or other text ), and unwrap it into the embedded JSON layer without the "label" (the label that was the target/destination) 
# returned data is the text-ified JSON without the wrap.
def json_unwrap_with_target(wrappeddata):
    try:   # in case it's not actually JSON 
        wrapper = json.loads(wrappeddata)
        target = wrapper['_target']
        if '_priority' in wrapper:
            priority = wrapper['_priority']
        else:
            priority = 1
        data = wrapper['data']
        cleaned = json.dumps(data,indent=2,sort_keys=True)    
        return (target,cleaned,priority)
    except: 
        print "CRITICAL json_unwrap_with_target FAILED: "+str(wrappeddata)
        return ( False, False)
    

def queue_ping(q,name):
            # ping central thread to tell them we are still here...
            ping = {} 
            ping['time']=int(time.time())
            ping['pid'] = os.getpid()
            ping['name'] = name   
            ping['procname'] = multiprocessing.current_process().name
            q.put(1,json_wrap_with_target(ping,'watchtasks'))

# note:  (target,cleaned,priority) =  json_unwrap_with_target(json_wrap_with_target('{ "some": "data"}'))  should return: 'target' = logging, and  cleaned =  '{ "some": "data" }'

        #z = '{ "some": "json"}'
        #a = json_wrap_with_target(z)
        #print repr(a)
        #(b,c,p) = json_unwrap_with_target(a)
        #print repr(b)
        #print repr(c)


# just helps in debugging, not critical to ops of system: 
def log_to_file(file,data):

    # internal static counter just for this function to increment etc, and this is how we initialise it on the first use...
    if not hasattr(log_to_file, "counter"):
         log_to_file.counter = 0  # it doesn't exist yet, so initialize it


    if sys.platform == 'win32':
        rootfolder = 'X:\\WebConfigServer\\'
        jsonfolder = rootfolder+'json\\'
    else:
        rootfolder = '/root/WebConfigServer/'
        jsonfolder = rootfolder+'json/'

    log_to_file.counter += 1  

    t = str(log_to_file.counter)
    t = t.zfill(4)

    file_put_contents(jsonfolder+t+file,data)

## for testing stuff - not really used
#if __name__ == '__main__':

#    data  = "132356456"
#    log_to_file("test123.txt",data)
