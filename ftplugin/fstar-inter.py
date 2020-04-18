import sys
import re
import vim
import json
from subprocess import PIPE,Popen
from threading import Thread
from queue import Queue, Empty
fstarpath='fstar.exe'
fstarbusy=0
fstarcurrentline=0
fstarpotentialline=0
fstarrequestline=0
fstaranswer=None
fstarupdatehi=False
fstarmatch=None
fst=None
interout=None
fstar_window=None
query_id=1

ON_POSIX = 'posix' in sys.builtin_module_names

def fstar_write(message):
    orig_window = vim.current.window.number
    winnr = fstar_window()
    vim.command("set modifiable")
    vim.command("normal! 1GdG")
    vim.buffers[winnr].append(message,0)
    vim.command("set nomodifiable")
    vim.command(str(orig_window)+"wincmd w")

def fstar_reset_hi() :
    global fstarmatch
    if fstarmatch != None:
        vim.command("call matchdelete("+str(fstarmatch)+")")
    fstarmatch=None
    return

def fstar_add_hi(pos) :
    global fstarmatch
    if pos >= 1 :
        fstarmatch=int(vim.eval("matchadd('FChecked','\\%<"+str(pos+1)+"l')"))
    return

def fstar_update_hi(newpos) :
    fstar_reset_hi()
    fstar_add_hi(newpos)
    return

def fstar_update_marker(newpos) :
    vim.command('exe "normal! ' + str(newpos) + 'G1|mv\\<C-o>"')
    return

#no waiting read as in http://stackoverflow.com/a/4896288/2598986
def fstar_enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()

def fstar_readinter () :
    global interout
    try : line = interout.get_nowait()
    except Empty :
        return None
    else :
        return json.loads(line)

def fstar_writeinter (s) :
    global fst
    print(json.dumps(s)+"\n")
    fst.stdin.write(json.dumps(s)+"\n")

def fstar_init (fbuffer,window_creater) :
    global fst,interout, fstar_window, fstar_buffer
    fstar_buffer = fbuffer
    fstar_window = window_creater
    fst=Popen([fstarpath, fstar_buffer.name, '--ide'],stdin=PIPE, stdout=PIPE,stderr=PIPE, bufsize=1,universal_newlines=True, close_fds=ON_POSIX)
    interout=Queue()
    t=Thread(target=fstar_enqueue_output,args=(fst.stdout,interout))
    t.daemon=True
    t.start()

def fstar_reset() :
    global fstarbusy,fstarcurrentline,fstarpotentialline,fstaranswer,fstarupdatehi,fstarmatch
    fstarbusy=0
    fstarcurrentline=0
    fstarpotentialline=0
    fstaranswer=None
    fstarupdatehi=False
    fstar_reset_hi()
    message = {"query-id":str(query_id), "query": "exit", "args":{}}
    fstar_write(message)
    fstar_init()
    fstar_write('Interaction reset')


def fstar_test_code (code,keep,quickcheck=False) :
    global fstarbusy,fst, query_id
    if fstarbusy == 1 :
        return 'Already busy'
    fstarbusy = 1
    message = {"query-id": str(query_id), "query":"push", "args":{"kind":"full", "code":code+"\n", "line": fstarcurrentline+1, "column":0}}
    query_id +=1
    if quickcheck:
        message["args"]["kind"]="lax"
    if not keep :
        message["query"] = "peek"
    fstar_writeinter(message)
    return ''

def fstar_lookup(symbol):       # need to remove escaping properly
    global fstarbusy, query_id
    if fstarbusy == 1:
        return 'Already busy'
    fstarbusy = 1
    message = {"query-id": str(query_id), "query": "lookup", "args": {"symbol": symbol[1:-1], "requested-info": ["name", "defined-at", "documentation", "type", "definition"]}}
    query_id +=1
    fstar_writeinter(message)

def fstar_compute(term):
    global fstarbusy, query_id
    if fstarbusy == 1:
        return 'Already busy'
    fstarbusy = 1
    message = {"query-id": str(query_id), "query": "compute", "args": {"term": term[1:-1]}}
    query_id +=1
    fstar_writeinter(message)

def fstar_search(terms):
    global fstarbusy, query_id
    if fstarbusy == 1:
        return 'Already busy'
    fstarbusy = 1
    message = {"query-id": str(query_id), "query": "search", "args": {"terms": terms[1:-1]}}
    query_id +=1
    fstar_writeinter(message)

def fstar_convert_answer(ans) :
    global fstarrequestline
    res = re.match(r"\<input\>\((\d+)\,(\d+)\-(\d+)\,(\d+)\)\: (.*)",ans)
    if res == None :
        return ans
    return '(%d,%s-%d,%s) : %s' % (int(res.group(1))+fstarrequestline-1,res.group(2),int(res.group(3))+fstarrequestline-1,res.group(4),res.group(5))

def fstar_gather_answer () :
    global fstarbusy,fst,fstaranswer,fstarpotentialline,fstarcurrentline,fstarupdatehi, query_id
    if fstarbusy == 0 :
        return 'No verification pending'
    fstaranswer = []
    line=fstar_readinter()
    while line != None :
        print(line)
        if(line["kind"] == "response" and line["query-id"] == str(query_id-1)) :
            fstarbusy=0
            if line["status"]=='success':
                fstarcurrentline=fstarpotentialline
                if fstarupdatehi :
                    fstar_update_hi(fstarcurrentline)
                    fstar_update_marker(fstarcurrentline+1)
                #fstaranswer += [(x["level"] +": "+x["message"]).split("\n") for x in line["response"]]
                fstaranswer += [str(line["response"]).split("\n")]
                return [item for sublist in fstaranswer for item in sublist ]
            if line["status"] == 'failure' :
                fstarpotentialline=fstarcurrentline
                #fstaranswer += [(x["level"] +": "+x["message"] +" " + ", ".join([str(y["beg"]) + " " + str(y["end"]) if y["fname"] == "<input>" else "" for y in x["ranges"]])).split("\n") for x in line["response"]]
                fstaranswer += [str(line["response"]).split("\n")]
                return [item for sublist in fstaranswer for item in sublist ]
        if(line["kind"] == "message" and line["level"] == "progress"):
            try:
                fstaranswer.append(("progress: "+ " ".join(line["contents"].values())).split("\n"))
            except TypeError:
                pass
        line=fstar_readinter()
    return 'Busy'

def fstar_vim_query_answer () :
    r = fstar_gather_answer()
    if r != None :
        fstar_write(r)

def fstar_get_range(firstl,lastl) :
    lines = vim.eval("getline(%s,%s)"%(firstl,lastl))
    lines = lines + ["\n"]
    code = "\n".join(lines)
    return code


def fstar_get_selection () :
    firstl = int(vim.eval("getpos(\"'<\")")[1])
    endl = int(vim.eval("getpos(\"'>\")")[1])
    lines = vim.eval("getline(%d,%d)"%(firstl,endl))
    lines = lines +  ["\n"]
    code = "\n".join(lines)
    return code


def fstar_vim_test_code () :
    global fstarrequestline, fstaranswer
    global fstarupdatehi
    if fstarbusy == 1 :
        fstar_write('Already busy')
        return
    fstaranswer=''
    fstarrequestline = int(vim.eval("getpos(\"'<\")")[1])
    code = fstar_get_selection()
    fstarupdatehi=False
    fstar_test_code(code,False)
    fstar_write('Test of selected code launched')

def fstar_vim_until_cursor (quick=False) :
    global fstarcurrentline,fstarpotentialline,fstarrequestline,fstarupdatehi, fstaranswer
    if fstarbusy == 1 :
        fstar_write('Already busy')
        return
    fstaranswer = ''
    vimline = int(vim.eval("getpos(\".\")")[1])
    if vimline <= fstarcurrentline :
        fstar_write('Already checked')
        return
    firstl = fstarcurrentline+1
    fstarrequestline=firstl
    endl = vimline
    code = fstar_get_range(firstl,endl)
    fstarpotentialline=endl
    fstarupdatehi=True
    fstar_test_code(code,True,quick)
    if quick :
        fstar_write('Quick test until this point launched')
    else :
        fstar_write('Test until this point launched')

def fstar_vim_get_answer() :
    global fstaranswer
    fstar_write(fstaranswer)

def fstar_get_current_line () :
    global fstarcurrentline
    fstar_write(fstarcurrentline)
