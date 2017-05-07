from time import sleep
from datetime import datetime
from Queue import Empty
from multiprocessing import Queue as ProcessQueue
# ideas from here http://stackoverflow.com/questions/1354204/how-to-implement-a-multiprocessing-priority-queue-in-python
import time

class SimplePriorityQueue(object):
    '''
    Simple priority queue that works with multiprocessing. Only a finite number 
    of priorities are allowed. Adding many priorities slow things down. 

    Also: no guarantee that this will pull the highest priority item 
    out of the queue if many items are being added and removed. Race conditions
    exist where you may not get the highest priority queue item.  However, if 
    you tend to keep your queues not empty, this will be relatively rare.
    '''
    def __init__(self, num_priorities=2): #, default_sleep=.2):
        self.num_priorities = num_priorities
        self.queues = []
        #self.default_sleep = default_sleep
        for i in range(0, num_priorities):
            self.queues.append(ProcessQueue())

    def __repr__(self):
        return "<Queue with %d priorities  %s>"%(len(self.queues), 
                    ", ".join(map(lambda (i, q): "%d "%(i), 
                                enumerate(self.queues))))

    # this impl of qsize() does not work on OSX dies to a known python issue, but linux, windows etc is ok. TODO rework this to not use qsize()
    #qsize = lambda(self): sum(map(lambda q: q.qsize(), self.queues))

    def get(self, block=True, timeout=None):
        start = datetime.utcnow()
        while True:
            for i in range(0, self.num_priorities):
            #for q in self.queues: # iterate from 0 ( highest priority ) to the others , such as 1. with lower priority.
                q = self.queues[i]
                try:
                    x =  q.get(block=False)
                    return x
                except Empty:
                    pass
            if not block:
                raise Empty
            if timeout and (datetime.utcnow()-start).total_seconds > timeout:
                raise Empty
            if timeout:
                time_left = (datetime.utcnow()-start).total_seconds - timeout
                #sleep(time_left/4)
            else:
                pass #sleep(self.default_sleep)

    get_nowait = lambda(self): self.get(block=False)

    # if any of the queues inside a non-empty, we are non-empty.
    def empty(self):
           empty = True
           for q in self.queues:
                if not q.empty():
                    empty = False
           return empty
        
 
    def put(self, priority, obj, block=False, timeout=None):
        if priority < 0 or priority >= len(self.queues):
            #print("Priority %d out of range: from: 0 to %d are OK "% ( priority, len(self.queues)-1 ) ) 
            raise LookupError 
        # Block and timeout don't mean much here because we never set maxsize
        x = self.queues[priority].put(obj)
        return x

# below here is a basic test suite for the SimplePriorityQueue, try it with 'python SimplePriorityQueue.py' :-) 
if __name__ == '__main__':
    input_queue = SimplePriorityQueue(2) # 2 priorities.

    if input_queue.empty() == True:
        print "OK: empty queue apears to empty" 
    else:
        print "ERR"

    testdata = 'something to test';  
    priority = 1;
    input_queue.put(priority,testdata)
    if  input_queue.empty() == False:
        print "OK: queue has ONE entry" 
    else:
        print "ERR"

    testdata = 'something high priority';  
    priority = 0;
    input_queue.put(priority,testdata)
    if  input_queue.empty() == False:
        print "OK: queue has TWO entries" 
    else:
        print "ERR"

    time.sleep(1)

    # should give us the high priority one first, as it's higher priority.
    x = input_queue.get_nowait()
    if  x == 'something high priority':
        print "OK: queue removed an item ok, and it was the high-priority one." 
    else:
        print "ERR"

    # testing incorrect priority passed in.
    testdata = 'something with a bad priority';  
    priority = 4;
    try:
        input_queue.put(priority,testdata)
        print "ERR exception not triggered"
    except LookupError as e:
        print "OK: queue triggered exception as it should have on bad priority"


    # empty the queue, and then over-empty it.
        input_queue.put(1,'erterta')
        input_queue.put(1,'ertertb')
        input_queue.put(0,'ertertc')
        input_queue.put(0,'ertertd')
    x = input_queue.get_nowait()
    x = input_queue.get_nowait()
    x = input_queue.get_nowait()
    x = input_queue.get_nowait()
    x = input_queue.get_nowait()
    try:
        x = input_queue.get_nowait()
    except Empty as e:
        print "queue is Empty as it should be"

    #x = input_queue.get_nowait()
    if  input_queue.empty() == True :
        print "OK: queue went to zero, but not beyond." 
    else:
        print "ERR"


     
    # other unit tests could be add ed here.
    print "If you see ERR anywhere except this line, there was a problem with the test suite"
