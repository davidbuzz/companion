from contextlib import contextmanager
import sys
import time
import os
if  sys.platform == 'win32':
    from file_utils import WinAppRoot  
else:
    from file_utils import AppRoot  


class CustomPrint():
    def __init__(self, stdout, pre, logfilename):
        self.old_stdout = stdout
        self.pre = pre
        self.linecount = 0;
        self.logfilename = logfilename
        if sys.platform == 'win32':
            self.dirname = WinAppRoot+'\\logs\\'
        else:
            self.dirname =  AppRoot+'/logs/'
        self.reopen()  # always start a clean startup with a clean log , it's easier. 

    def write(self, text):
        t =  time.strftime("%Y-%m-%d %H:%M:%S> ", time.gmtime()) # with a bit of ws around it.
        if len(text.rstrip()):
            self.old_stdout.write(self.pre + text+"\n")
            self.logfile.write(self.pre+t+text+"\n")  # we timestamp logs, but not stdout.
            self.flush()  # flush after every write()
            self.linecount = self.linecount  +1
        if self.linecount > 50000:   # maybe around the 10-20MB file size? 
            self.reopen()
            self.linecount = 0

    def reopen(self):
            try:
                self.logfile.flush()
                self.logfile.close()
            except:
                pass
            # drop 5, move 4 to 5
            self.pushfiles(self.dirname+self.logfilename+".4",self.dirname+self.logfilename+".5") 
            self.pushfiles(self.dirname+self.logfilename+".3",self.dirname+self.logfilename+".4") 
            self.pushfiles(self.dirname+self.logfilename+".2",self.dirname+self.logfilename+".3") 
            self.pushfiles(self.dirname+self.logfilename+".1",self.dirname+self.logfilename+".2") 
            self.pushfiles(self.dirname+self.logfilename     ,self.dirname+self.logfilename+".1") 
            self.logfile = open(self.dirname+self.logfilename , 'a')

    def pushfiles(self, xfrom, xto):
            # drop file 5
            try:
                os.unlink(xto) #cleanup old file if present
            except:
                pass
            # move file 4 to file 5
            try:
                os.rename(xfrom, xto) 
            except:
                pass



    def flush(self):
        self.old_stdout.flush()
        self.logfile.flush()

################################################################################
@contextmanager
def modified_stdout(pre = "MODIFIED> ", logfile='WebConfigServer_standard.log'):
    import sys
    old_stdout = sys.stdout
    sys.stdout = CustomPrint(old_stdout, pre, logfile)
    try:
        yield
    finally:
        sys.stdout = old_stdout
################################################################################

@contextmanager
def unmodified_stdout(pre = "MODIFIED> ", logfile='WebConfigServer_standard.log'):
    yield

if __name__ == '__main__':
    #
    sys.stdout = CustomPrint(sys.stdout,"STDOUTCONTEXT> ","WebConfigServer_main.log")
    while True:
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        print "voop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voopvoop voop voop"
        
