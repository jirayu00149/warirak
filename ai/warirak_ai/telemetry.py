"""Persistent, retry-safe telemetry outbox. Does not run AI or control motors."""
import argparse,json,os,sqlite3,sys,time,urllib.request,urllib.error,urllib.parse,uuid
from pathlib import Path
def validate_url(value):
    u=urllib.parse.urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in ('','/') or (u.scheme!='https' and not(u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1'))):raise ValueError('Use HTTPS origin, or HTTP loopback for a local backend')
    if not u.hostname:raise ValueError('Backend hostname is missing')
    return value.rstrip('/')
def open_outbox(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at_ms INTEGER NOT NULL)');db.commit();return db
def enqueue(db,kind,payload):
    if kind not in ('telemetry','collections'):raise ValueError('Unsupported event type')
    data=dict(payload)
    if kind=='collections':
        if data.get('collection_confirmed') is not True or data.get('source') not in (None,'hardware'):raise ValueError('Only physically confirmed hardware collections may enter this endpoint')
        data.setdefault('event_id','collection-'+str(uuid.uuid4()))
        for name in ('mission_id','occurred_at'):
            if not data.get(name):raise ValueError('Missing '+name)
        event_id=data['event_id']
    else:
        for name in ('observed_at','battery_percent','state'):
            if name not in data:raise ValueError('Missing '+name)
        event_id='telemetry-'+str(uuid.uuid4())
    encoded=json.dumps(data,sort_keys=True,separators=(',',':'))
    existing=db.execute('SELECT payload FROM outbox WHERE id=?',(event_id,)).fetchone()
    if existing and existing[0]!=encoded:raise ValueError('Same event_id has a different payload')
    db.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?)',(event_id,kind,encoded,int(time.time()*1000)));db.commit();return event_id
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None
def flush(db,url,device_token,limit=100):
    url=validate_url(url)
    if not device_token:raise ValueError('Device token environment variable is missing')
    opener=urllib.request.build_opener(NoRedirect());sent=0
    for event_id,kind,payload in db.execute('SELECT id,kind,payload FROM outbox ORDER BY created_at_ms,id LIMIT ?',(limit,)).fetchall():
        headers={'Content-Type':'application/json','Authorization':'Bearer '+device_token}
        request=urllib.request.Request(url+'/api/device/'+kind,data=payload.encode(),headers=headers,method='POST')
        try:
            with opener.open(request,timeout=10) as response:
                result=json.loads(response.read(1048576))
                if response.status not in (200,201):raise RuntimeError('API did not acknowledge event')
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'HTTP {error.code}: event remains queued; check device token, backend URL or immutable ID conflict') from None
        db.execute('DELETE FROM outbox WHERE id=?',(event_id,));db.commit();sent+=1
    return sent
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--spool',default='data/telemetry-outbox.sqlite');sub=parser.add_subparsers(dest='command',required=True)
    add=sub.add_parser('enqueue');add.add_argument('--kind',choices=['telemetry','collections'],required=True);add.add_argument('--input',required=True)
    send=sub.add_parser('flush');send.add_argument('--url',required=True);send.add_argument('--device-token-env',default='WARIRAK_DEVICE_TOKEN')
    args=parser.parse_args();db=open_outbox(args.spool)
    try:
        if args.command=='enqueue':result={'queued_id':enqueue(db,args.kind,json.loads(Path(args.input).read_text(encoding='utf-8')))}
        else:result={'sent':flush(db,args.url,os.environ.get(args.device_token_env))}
        result['remaining']=db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0];print(json.dumps(result))
    finally:db.close()
if __name__=='__main__':main()
