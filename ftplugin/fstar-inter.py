import sys
import re
import vim
import json
from subprocess import PIPE,Popen
from threading import Thread
from queue import Queue, Empty
import numbers

ON_POSIX = 'posix' in sys.builtin_module_names

class Fstar:
    fstarpath='fstar.exe'
    fstarbusy=0
    fstaranswer = []
    fstarcurrentline=0
    fstarpotentialline=0
    fstarrequestline=0
    fstarupdatehi=False
    fstarmatch=None
    fst=None
    interout=None
    fstar_window=None
    query_id=1
    query = None
    keep = False

    def __init__ (self, fbuffer, window_creater) :
        self.fstar_buffer = fbuffer
        self.fstar_window = window_creater
        self.fst=Popen([self.fstarpath, self.fstar_buffer.name, '--ide'],stdin=PIPE, stdout=PIPE,stderr=PIPE, bufsize=1,universal_newlines=True, close_fds=ON_POSIX)
        self.interout=Queue()
        t=Thread(target=self.fstar_receive,args=(self.fst.stdout,self.interout))
        t.daemon=True
        t.start()

    def fstar_print(self, message):
        orig_window = vim.current.window.number
        winnr = self.fstar_window()
        vim.command("set modifiable")
        if self.keep:
            line = int(vim.eval('line("$")'))
        else:
            vim.command("normal! 1GdG")
            line = 0
        vim.buffers[winnr].append(message, line)
        vim.command("set nomodifiable")
        vim.command(str(orig_window)+"wincmd w")

    def fstar_reset_hi(self) :
        if self.fstarmatch != None:
            vim.command("call matchdelete("+str(self.fstarmatch)+")")
        self.fstarmatch=None
        return

    def fstar_add_hi(self, pos) :
        if pos >= 1 :
            self.fstarmatch=int(vim.eval("matchadd('FChecked','\\%<"+str(pos+1)+"l')"))
        return

    def fstar_update_hi(self, newpos) :
        self.fstar_reset_hi()
        self.fstar_add_hi(newpos)
        return

    def fstar_update_marker(self, newpos) :
        vim.command('exe "normal! ' + str(newpos) + 'G1|mv\\<C-o>"')
        return

    #no waiting read as in http://stackoverflow.com/a/4896288/2598986
    def fstar_receive(self, out, queue):
        for line in iter(out.readline, b''):
            queue.put(line)
        out.close()

    def fstar_read_received (self ) :
        try : line = self.interout.get_nowait()
        except Empty :
            return None
        else :
            return json.loads(line)

    def fstar_send (self, s) :
        print(json.dumps(s)+"\n")
        self.fst.stdin.write(json.dumps(s)+"\n")

    def fstar_reset(self ) :
        self.fstar_reset_hi()
        message = {"query-id":str(self.query_id), "query": "exit", "args":{}}
        self.fstar_send(message)
        self.fstar_print('Interaction reset')

    def fstar_test_code (self, code,keep,quickcheck=False) :
        if self.fstarbusy == 1 :
            return 'Already busy'
        self.fstarbusy = 1
        message = {"query-id": str(self.query_id), "query":"push", "args":{"kind":"full", "code":code+"\n", "line": self.fstarcurrentline+1, "column":0}}
        self.query_id +=1
        if quickcheck:
            message["args"]["kind"]="lax"
        if not keep :
            message["query"] = "peek"
        self.fstar_send(message)
        return ''

    def fstar_lookup(self, symbol):       # need to remove escaping properly
        if self.fstarbusy == 1:
            return 'Already busy'
        self.fstarbusy = 1
        message = {"query-id": str(self.query_id), "query": "lookup", "args": {"symbol": symbol[1:-1], "requested-info": ["name", "defined-at", "documentation", "type", "definition"]}}
        self.query_id +=1
        self.fstar_send(message)

    def fstar_compute(self, term):
        if self.fstarbusy == 1:
            return 'Already busy'
        self.fstarbusy = 1
        message = {"query-id": str(self.query_id), "query": "compute", "args": {"term": term[1:-1]}}
        self.query_id +=1
        self.fstar_send(message)

    def fstar_search(self, terms):
        if self.fstarbusy == 1:
            return 'Already busy'
        self.fstarbusy = 1
        message = {"query-id": str(self.query_id), "query": "search", "args": {"terms": terms[1:-1]}}
        query_id +=1
        self.fstar_send(message)

#    def fstar_convert_answer(self, ans) :
#        res = re.match(r"\<input\>\((\d+)\,(\d+)\-(\d+)\,(\d+)\)\: (.*)",ans)
#        if res == None :
#            return ans
#        return '(%d,%s-%d,%s) : %s' % (int(res.group(1))+self.fstarrequestline-1,res.group(2),int(res.group(3))+self.fstarrequestline-1,res.group(4),res.group(5))

    def fstar_print_pretty(self, line):
        fstaranswer = []
        if(line["kind"] == "message"):
            try:
                fstaranswer = (line["level"] +" : "+ " ".join(line["contents"].values())).split("\n")
            except TypeError:
                pass
            finally:
                self.fstar_print(fstaranswer)
                self.keep = True
        elif line["kind"] == "response": # assuming query id is correct because so far everyting is sequential
            fstaranswer = self.response_to_str(line["response"]).split("\n")
            self.fstar_print(fstaranswer)
            self.keep = False
        elif line["kind"] == "protocol-info":
            #fstaranswer = ("version: "+str(line["version"]) + "\nfeatures: "+", ".join(line["features"])).split("\n")
            #self.fstar_print(fstaranswer)
            #self.keep = True
            pass

    def response_to_str(self, response):
        if(type(response) == dict):
            answer = ""
            for (key, value) in response.items():
                if key == "ranges":
                    for res  in value:
                        if res["fname"] == "<input>":
                            answer += "beg : "+" ".join([str(item) for item in res["beg"]])
                            answer += "\n"
                            answer += "end : "+" ".join([str(item) for item in res["end"]])
                            answer += "\n"
                        else:
                            answer += "fname : " + self.response_to_str(res["fname"]) + "\n"
                elif value is not None:
                    answer += str(key) + " : " + self.response_to_str(value) + "\n"
            return answer
        elif (type(response) == str):
            return response
        elif isinstance(response, numbers.Real):
            return str(response)
        elif response is None:
            return ""
        else :
            return "\n".join([self.response_to_str(item) for item in response])


    def fstar_gather_answer (self ) :
        if self.fstarbusy == 0 :
            return 'No verification pending'
        line=self.fstar_read_received()
        while line != None :
            print(line)
            if(line["kind"] == "response" and line["query-id"] == str(self.query_id-1)) :
                self.fstarbusy=0
                if line["status"]=='success':
                    self.fstarcurrentline=self.fstarpotentialline
                    if self.fstarupdatehi :
                        self.fstar_update_hi(self.fstarcurrentline)
                        self.fstar_update_marker(self.fstarcurrentline+1)
                    #fstaranswer += [(x["level"] +": "+x["message"]).split("\n") for x in line["response"]]
                elif line["status"] == 'failure' :
                    self.fstarpotentialline=self.fstarcurrentline
                    #fstaranswer += [(x["level"] +": "+x["message"] +" " + ", ".join([str(y["beg"]) + " " + str(y["end"]) if y["fname"] == "<input>" else "" for y in x["ranges"]])).split("\n") for x in line["response"]]
                else:
                    self.fstar_print(line["status"])
                self.fstaranswer.append(line)
                return self.fstaranswer
            self.fstaranswer.append(line)
            line=self.fstar_read_received()
        return 'Busy'

    def fstar_vim_query_answer (self ) :
        r = self.fstar_gather_answer()
        if r != None :
            if(type(r) is str):
                self.fstar_print(r)
                return
            else:
                for line in r:
                    self.fstar_print_pretty(line)
                self.fstaranswer = []

    def fstar_get_range(self, firstl,lastl) :
        lines = vim.eval("getline(%s,%s)"%(firstl,lastl))
        lines = lines + ["\n"]
        code = "\n".join(lines)
        return code


    def fstar_get_selection (self ) :
        firstl = int(vim.eval("getpos(\"'<\")")[1])
        endl = int(vim.eval("getpos(\"'>\")")[1])
        lines = vim.eval("getline(%d,%d)"%(firstl,endl))
        lines = lines +  ["\n"]
        code = "\n".join(lines)
        return code


    def fstar_vim_test_code (self) :
        if self.fstarbusy == 1 :
            self.fstar_print('Already busy')
            return
        self.fstarrequestline = int(vim.eval("getpos(\"'<\")")[1])
        code = self.fstar_get_selection()
        self.fstarupdatehi=False
        self.fstar_test_code(code,False)
        self.fstar_print('Test of selected code launched')

    def fstar_vim_until_cursor (self, quick=False) :
        if self.fstarbusy == 1 :
            self.fstar_print('Already busy')
            return
        vimline = int(vim.eval("getpos(\".\")")[1])
        if vimline <= self.fstarcurrentline :
            self.fstar_print('Already checked')
            return
        firstl = self.fstarcurrentline+1
        self.fstarrequestline=firstl
        endl = vimline
        code = self.fstar_get_range(firstl,endl)
        self.fstarpotentialline=endl
        self.fstarupdatehi=True
        self.fstar_test_code(code,True,quick)
        if quick :
            self.fstar_print('Quick test until this point launched')
        else :
            self.fstar_print('Test until this point launched')

    def fstar_get_current_line (self) :
        self.fstar_print(self.fstarcurrentline)
