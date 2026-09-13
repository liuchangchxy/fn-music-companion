import argparse, hashlib, json, os, shutil, sqlite3, subprocess, time
from pathlib import Path

INCOMING = Path(os.getenv('INCOMING', '/music/incoming'))
LIBRARY = Path(os.getenv('LIBRARY', '/music/library'))
DB = Path(os.getenv('DB', '/data/music.db'))
NCM = os.getenv('NCM', '/usr/local/bin/ncmdump')
FPCALC = os.getenv('FPCALC', '/usr/local/bin/fpcalc')

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB)
    c.executescript('''create table if not exists tracks(id integer primary key,path text unique,sha256 text,chromaprint text,duration real,codec text,container text,bitrate integer,sample_rate integer,bit_depth integer,channels integer,file_size integer,title text,artist text,album text,album_artist text,track_number integer,status text,created_at text default current_timestamp,updated_at text default current_timestamp);
    create table if not exists jobs(id integer primary key,source_path text,current_stage text,status text,error text,retry_count integer default 0,created_at text default current_timestamp,updated_at text default current_timestamp);
    create table if not exists duplicate_groups(id integer primary key,track_a integer,track_b integer,similarity real,reason text,decision text,created_at text default current_timestamp);''')
    return c

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def probe(p):
    x=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)],capture_output=True,text=True,check=True)
    j=json.loads(x.stdout); s=next((x for x in j['streams'] if x.get('codec_type')=='audio'),{})
    return j.get('format',{}),s

def fingerprint(p):
    x=subprocess.run([FPCALC,'-json',str(p)],capture_output=True,text=True,check=True)
    return json.loads(x.stdout)

def scan():
    c=db(); n=0
    for p in LIBRARY.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in {'.mp3','.flac','.m4a','.aac','.ape','.wav','.ogg','.opus','.wma','.aiff','.wv','.tta','.mp4'}: continue
        old=c.execute('select id,sha256 from tracks where path=?',(str(p),)).fetchone()
        if old and old[1] == sha(p): continue
        try:
            f,s=probe(p); fp=fingerprint(p)
            c.execute('insert or replace into tracks(path,sha256,chromaprint,duration,codec,container,bitrate,sample_rate,bit_depth,channels,file_size,status) values(?,?,?,?,?,?,?,?,?,?,?,?)', (str(p),sha(p),fp.get('fingerprint'),float(f.get('duration') or 0),s.get('codec_name'),f.get('format_name'),int(f.get('bit_rate') or 0),int(s.get('sample_rate') or 0),int(s.get('bits_per_sample') or 0),int(s.get('channels') or 0),p.stat().st_size,'indexed'))
            n+=1; c.commit()
        except Exception as e: print('SCAN_ERROR',p,e)
    print('indexed',n); c.close()

def process(src):
    src=Path(src); INCOMING.mkdir(parents=True,exist_ok=True); LIBRARY.mkdir(parents=True,exist_ok=True)
    work=INCOMING/'.pipeline-work'; work.mkdir(exist_ok=True)
    job=db(); jid=job.execute('insert into jobs(source_path,current_stage,status) values(?,?,?)',(str(src),'detect','running')).lastrowid; job.commit()
    try:
        candidate=src
        cleanup=None
        if src.suffix.lower()=='.ncm':
            jobdir=work/(str(jid)); jobdir.mkdir(exist_ok=True)
            staged=jobdir/src.name; shutil.copy2(src,staged); cleanup=jobdir
            subprocess.run([NCM,str(staged)],check=True)
            outs=list(jobdir.glob(staged.stem+'.*'))
            candidate=next((x for x in outs if x.suffix.lower() in {'.flac','.mp3'}),None)
            if not candidate: raise RuntimeError('NCM conversion produced no audio')
        f,s=probe(candidate); h=sha(candidate); fp=fingerprint(candidate)
        same=job.execute('select path from tracks where sha256=? and status != "deleted"',(h,)).fetchone()
        if same:
            job.execute('update jobs set current_stage="dedupe",status="done" where id=?',(jid,)); job.commit()
            print('EXACT_DUPLICATE',same[0]); return
        rel=candidate.name; dest=LIBRARY/rel
        if dest.exists(): dest=LIBRARY/(candidate.stem+' '+h[:8]+candidate.suffix)
        os.replace(candidate,dest)
        job.execute('insert or replace into tracks(path,sha256,chromaprint,duration,codec,container,bitrate,sample_rate,bit_depth,channels,file_size,status) values(?,?,?,?,?,?,?,?,?,?,?,?)',(str(dest),h,fp.get('fingerprint'),float(f.get('duration') or 0),s.get('codec_name'),f.get('format_name'),int(f.get('bit_rate') or 0),int(s.get('sample_rate') or 0),int(s.get('bits_per_sample') or 0),int(s.get('channels') or 0),dest.stat().st_size,'pending_metadata'))
        job.execute('update jobs set current_stage="commit",status="done" where id=?',(jid,)); job.commit(); print('UNIQUE',dest)
    except Exception as e:
        job.execute('update jobs set status="failed",error=? where id=?',(repr(e),jid)); job.commit(); raise

def watch():
    scan()
    seen={}
    print('watching', INCOMING, flush=True)
    while True:
        for p in INCOMING.rglob('*'):
            if not p.is_file() or '.pipeline-work' in p.parts: continue
            if p.suffix.lower() not in {'.ncm','.mp3','.flac','.m4a','.aac','.ape','.wav','.ogg','.opus','.wma','.aiff','.wv','.tta','.mp4'}: continue
            try: key=(p.stat().st_size,p.stat().st_mtime_ns)
            except FileNotFoundError: continue
            if seen.get(str(p)) == key: continue
            seen[str(p)]=key
            time.sleep(2)
            try: process(p)
            except Exception as e: print('PROCESS_ERROR',p,e,flush=True)
        time.sleep(30)

if __name__=='__main__':
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd'); sub.add_parser('scan-library'); sub.add_parser('watch'); p=sub.add_parser('process'); p.add_argument('path'); a=ap.parse_args()
    if a.cmd=='scan-library': scan()
    elif a.cmd=='watch': watch()
    elif a.cmd=='process': process(a.path)
    else: ap.print_help()
