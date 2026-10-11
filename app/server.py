"""Local application server. Credentials remain in the configured Skill environment."""
from __future__ import annotations
import copy, hashlib, json, mimetypes, os, re, shutil, subprocess, sys, threading, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from ingest import source_name, media_key, coverage_note, material_text, read_url, decode_image, read_image, parse_subtitles

APP = Path(__file__).resolve().parent
from paths import DATA, MEDIA, PORT, INSTANCE
DATA.mkdir(parents=True, exist_ok=True)
MEDIA.mkdir(parents=True, exist_ok=True)
STATE = DATA/'state.json'
LOCK = threading.RLock()
ACTIVE = None

def now(): return datetime.now(timezone.utc).isoformat()
def read(): return json.loads(STATE.read_text(encoding='utf-8'))
def save(s):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(STATE)
def key(url):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname: raise ValueError('请输入完整的 http 或 https 链接。')
    if media_key(url):return media_key(url)
    if p.hostname in ('www.xiaohongshu.com','xiaohongshu.com'):
        m=re.fullmatch(r'/(?:explore|discovery/item|user/profile/[0-9a-f]+)/([0-9a-f]+)',p.path.rstrip('/'))
        if m:return 'xhs:'+m.group(1)
    if p.hostname=='mp.weixin.qq.com':
        if p.path.startswith('/s/'):return p.hostname+p.path.rstrip('/')
        q=parse_qs(p.query)
        if all(x in q for x in ('__biz','mid','idx','sn')):
            return 'weixin:'+json.dumps({x:q[x] for x in ('__biz','mid','idx','sn')},sort_keys=True)
    return p.hostname.lower()+p.path.rstrip('/')+('?' + p.query if p.query else '')

def initialize():
    if STATE.exists():
        s=read()
        for m in s['sources']:
            m['source']=source_name(m['url'])
            m['coverage_note']=coverage_note(m)
            if m.get('ingest_status')=='reading':m.update(ingest_status='failed',ingest_error='上次读取中断，请重新读取。')
        for e in s['episodes']:
            if 'source_snapshots' not in e:
                req=DATA/'jobs'/e['id']/'request.json'
                snapshots=json.loads(req.read_text())['materials'] if req.exists() else [copy.deepcopy(m) for m in s['sources'] if m['id'] in e['source_ids']]
                for m in snapshots:m['coverage_note']=coverage_note(m)
                e['source_snapshots']=snapshots
        for j in s['jobs']:
            if j['status'] in ('drafting','synthesizing'):
                j.update(failed_stage='audio' if j['status']=='synthesizing' else 'draft',status='failed',error='上次制作中断了，内容已保留，可以重试。')
        save(s);return
    save({'sources':[], 'episodes':[], 'jobs':[]})

def public_state():
    s=read()
    for m in s['sources']:
        m['coverage_note']=coverage_note(m)
        m['characters']=len(m.get('text',''));m.pop('key',None)
    return s

def start_ingest(ident, images=None):
    def run():
        try:
            with LOCK:m=copy.deepcopy(next(x for x in read()['sources'] if x['id']==ident))
            if images is None:
                result=read_url(m['url'])
                with LOCK:
                    s=read();target=next(x for x in s['sources'] if x['id']==ident)
                    target.update(result);target.update(status='ready',ingest_status='complete',ingest_error='')
                    target['coverage_note']=coverage_note(target);save(s)
            else:
                for raw in images:
                    digest=hashlib.sha256(raw).hexdigest()
                    with LOCK:
                        target=next(x for x in read()['sources'] if x['id']==ident)
                        if any(n.get('sha256')==digest for n in target.get('image_notes',[])):continue
                    note=read_image(raw)
                    folder=MEDIA/'sources'/ident;folder.mkdir(parents=True,exist_ok=True)
                    filename=digest[:16]+'.jpg';(folder/filename).write_bytes(raw)
                    with LOCK:
                        s=read();target=next(x for x in s['sources'] if x['id']==ident)
                        notes=target.setdefault('image_notes',[])
                        notes.append({'index':len(notes)+1,'text':note,'image_url':'/media/sources/'+ident+'/'+filename,'sha256':digest,'method':'vision_model','captured_at':now()})
                        target['coverage']['images_read']=len(notes)
                        target['coverage_note']=coverage_note(target);target['status']='ready';save(s)
                with LOCK:
                    s=read();next(x for x in s['sources'] if x['id']==ident).update(ingest_status='complete',ingest_error='');save(s)
        except Exception as exc:
            with LOCK:
                s=read();m=next(x for x in s['sources'] if x['id']==ident)
                # Never expose provider errors, signed URLs, credentials, or raw response bodies.
                msg=str(exc) if isinstance(exc,ValueError) else '暂未读取成功。可重试，或通过浏览器读取、补充正文或字幕。'
                m.update(ingest_status='failed',ingest_error=msg[:180]);save(s)
    threading.Thread(target=run,daemon=True).start()

def start_worker(job_id,stage):
    global ACTIVE
    if ACTIVE: raise ValueError('有一期节目正在制作，请等它完成后再开始。')
    ACTIVE=job_id
    def run():
        global ACTIVE
        job_dir=DATA/'jobs'/job_id;job_dir.mkdir(parents=True,exist_ok=True)
        result_path=job_dir/(stage+'-result.json')
        try:
            with (job_dir/(stage+'.log')).open('w') as log:
                proc=subprocess.run([sys.executable,str(APP/'worker.py'),stage,str(job_dir)],stdout=log,stderr=log,timeout=900)
            if proc.returncode: raise RuntimeError('制作失败')
            result=json.loads(result_path.read_text())
            with LOCK:
                s=read();j=next(x for x in s['jobs'] if x['id']==job_id)
                if stage=='draft':j.update(status='review',draft=result,error='')
                else:
                    e={**result,'id':job_id,'created_at':now(),'source_ids':j['source_ids'],'listen_position':0,'listened':False,'theme':'olive','origin':'由收藏生成'}
                    s['episodes'].insert(0,e);j.update(status='complete',episode_id=job_id,error='')
                save(s)
        except Exception:
            failure=job_dir/'failure.json'
            reason=json.loads(failure.read_text()).get('message') if failure.exists() else '制作超时或进程中断。现有内容已保留，请检查服务连接后重试。'
            with LOCK:
                s=read();next(x for x in s['jobs'] if x['id']==job_id).update(status='failed',failed_stage=stage,error=reason);save(s)
        finally:
            with LOCK:ACTIVE=None
    threading.Thread(target=run,daemon=True).start()

def valid_draft(d, allowed_ids=None):
    if not isinstance(d,dict) or not isinstance(d.get('title'),str) or not 1<=len(d['title'])<=100:raise ValueError('请填写节目标题。')
    turns=d.get('turns',[])
    if not 2<=len(turns)<=80:raise ValueError('对话稿需要 2 到 80 段。')
    for t in turns:
        if t.get('speaker') not in ('甲','乙') or not isinstance(t.get('text'),str) or not 1<=len(t['text'])<=1800:raise ValueError('请检查每段对话的说话人和文字。')
    if {t['speaker'] for t in turns}!={'甲','乙'}:raise ValueError('双人对谈需要甲乙两位说话人。')
    if not all(isinstance(d.get(k),str) and d[k].strip() for k in ('subtitle','takeaway')):raise ValueError('缺少节目简介或核心观点。')
    points=d.get('points')
    if not isinstance(points,list) or not 1<=len(points)<=8:raise ValueError('图文精华需要至少一个章节。')
    used=set()
    for p in points:
        if not isinstance(p,dict) or not all(isinstance(p.get(k),str) and p[k].strip() for k in ('title','summary')):raise ValueError('章节标题或摘要无效。')
        ids=p.get('source_ids',[]);diagram=p.get('diagram')
        if not isinstance(ids,list) or not ids or not all(isinstance(x,str) for x in ids):raise ValueError('章节缺少来源。')
        used.update(ids)
        if not isinstance(diagram,list) or not 2<=len(diagram)<=5 or not all(isinstance(x,str) and 0<len(x)<=30 for x in diagram):raise ValueError('请检查章节图示。')
        if not isinstance(p.get('turn_index'),int) or not 0<=p['turn_index']<len(turns):raise ValueError('节目笔记的章节位置无效，请重新整理。')
    if allowed_ids is not None and used!=set(allowed_ids):raise ValueError('章节来源必须覆盖所选素材，且不能包含未知来源。')
    if [p['turn_index'] for p in points]!=sorted(p['turn_index'] for p in points):raise ValueError('章节应按对话顺序排列。')
    return d

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def json(self,status,obj):
        data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',len(data));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):return self.json(403,{'error':'本地服务不可从此地址访问。'})
        path=unquote(urlparse(self.path).path)
        if path=='/api/health':return self.json(200,{'app':'listen-later','version':'1.0.0','instance':INSTANCE})
        if path=='/api/state':
            with LOCK:return self.json(200,public_state())
        if path.startswith('/api/progress/'):
            ident=path.rsplit('/',1)[-1]
            if not re.fullmatch(r'[a-f0-9]{12}',ident):return self.json(404,{})
            f=DATA/'jobs'/ident/'progress.json'
            try:return self.json(200,json.loads(f.read_text()))
            except (FileNotFoundError,json.JSONDecodeError):return self.json(200,{})
        if path=='/':path='/index.html'
        root=MEDIA if path.startswith('/media/') else APP
        relative=path.removeprefix('/media/') if root==MEDIA else path.lstrip('/')
        target=(root/relative).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.suffix not in ('.html','.css','.js','.mp3','.svg','.md','.png','.jpg','.webp'):return self.json(404,{'error':'未找到页面。'})
        if target.name in ('server.py','worker.py'):return self.json(404,{})
        size=target.stat().st_size;start,end=0,size-1
        requested=self.headers.get('Range','')
        if requested:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
            if not match:return self.json(416,{})
            start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
            if start>end:return self.json(416,{})
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type',mimetypes.guess_type(target)[0] or 'application/octet-stream')
        self.send_header('Content-Length',end-start+1);self.send_header('Accept-Ranges','bytes')
        if requested:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Cache-Control','no-cache');self.end_headers()
        with target.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining:
                b=f.read(min(65536,remaining))
                if not b:break
                try:self.wfile.write(b)
                except (BrokenPipeError,ConnectionResetError):break
                remaining-=len(b)
    def do_POST(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):return self.json(403,{})
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):return self.json(403,{})
        if 'application/json' not in self.headers.get('Content-Type',''):return self.json(415,{})
        try:
            size=int(self.headers.get('Content-Length',0))
            if size>30000000:raise ValueError('内容太长，请分批添加。')
            body=json.loads(self.rfile.read(size))
            with LOCK:result=self.action(urlparse(self.path).path,body)
            self.json(200,result)
        except (ValueError,KeyError,StopIteration,TypeError) as e:self.json(400,{'error':str(e) or '内容不完整，请检查后再试。'})
        except Exception:self.json(500,{'error':'保存未成功，请重试。'})
    def action(self,path,b):
        s=read()
        if path in ('/api/source/read','/api/source/images'):
            m=next(x for x in s['sources'] if x['id']==b['id'])
            if m.get('ingest_status')=='reading':raise ValueError('这篇内容正在读取，请稍候。')
            images=None
            if path.endswith('/images'):
                files=b.get('files',[])
                if not 1<=len(files)<=8:raise ValueError('一次添加 1–8 张图片。')
                images=[decode_image(f) for f in files]
                existing={n.get('sha256') for n in m.get('image_notes',[])}
                distinct={hashlib.sha256(raw).hexdigest():raw for raw in images}
                images=[raw for digest,raw in distinct.items() if digest not in existing]
                total=m.get('coverage',{}).get('images_total')
                if total and len(m.get('image_notes',[]))+len(images)>total:raise ValueError('已整理的配图加本次图片超过原文总数，请检查是否重复选择。')
            m.update(ingest_status='reading',ingest_error='');save(s);start_ingest(m['id'],images)
            return {'id':m['id'],'status':'reading'}
        if path=='/api/source/subtitles':
            m=next(x for x in s['sources'] if x['id']==b['id'])
            if m.get('ingest_status')=='reading':raise ValueError('请等待读取完成。')
            segments=parse_subtitles(str(b['text']))
            m.update(segments=segments,kind='video',text='\n'.join('['+str(round(x['start'],1))+'s] '+x['text'] for x in segments),retrieval='user_subtitles',status='ready',ingest_status='complete',ingest_error='')
            m['coverage'].update(video_transcribed=True,body=False,video_frames_read=0)
            m['coverage_note']=coverage_note(m);save(s);return {'id':m['id'],'segments':len(segments)}
        if path=='/api/source/evidence':
            record=b['record']
            if record.get('method')!='browser_use' or record.get('status','read')!='read' or not record.get('coverage',{}).get('body'):
                raise ValueError('需要真实读取到正文的浏览器证据。')
            text=str(record.get('text','')).strip();title=str(record.get('title','')).strip();url=record['url'];k=key(url)
            if len(text)<40 or not title or not record.get('captured_at'):raise ValueError('正文、标题或读取时间不完整。')
            m=next((x for x in s['sources'] if x['key']==k),None)
            if not m:
                m={'id':uuid.uuid4().hex[:12],'key':k,'created_at':now(),'kind':'article'};s['sources'].insert(0,m)
            m.update(title=title[:150],url=url,text=text[:50000],source='小红书' if 'xiaohongshu.com' in urlparse(url).hostname else '网页',
                     author=record.get('author',''),status='ready',retrieval='browser_use',coverage=record['coverage'],
                     coverage_note='已读正文；配图和视频以实际读取范围为准',captured_at=record['captured_at'])
            m['source']=source_name(url)
            if 'image_notes' in record:
                notes=record['image_notes']
                if not isinstance(notes,list) or len(notes)>30:raise ValueError('图片读取记录格式无效。')
                for n in notes:
                    asset=n.get('image_url','')
                    if not isinstance(n.get('index'),int) or n['index']<1 or not isinstance(n.get('text'),str) or not n['text'].strip() or not n.get('captured_at'):raise ValueError('缺少图片读取内容或时间。')
                    if asset and (not re.fullmatch(r'/media/sources/[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+\.(png|jpg|webp)',asset) or not (MEDIA/asset.removeprefix('/media/')).is_file()):raise ValueError('图片证据文件不存在。')
                if len({n['index'] for n in notes})!=len(notes):raise ValueError('图片序号重复。')
                if m['coverage'].get('images_total') and any(n['index']>m['coverage']['images_total'] for n in notes):raise ValueError('图片序号超过已确认的总数。')
                m['image_notes']=notes;m['coverage']['images_read']=len(notes)
            m['coverage_note']=coverage_note(m)
            save(s);return {'id':m['id'],'status':'ready'}
        if path=='/api/demo':
            existing=next((e for e in s['episodes'] if e['id']=='demo'),None)
            if existing:return {'id':'demo','duplicate':True}
            sample=json.loads((APP.parent/'examples/demo/episode.json').read_text())
            sample['created_at']=now()
            s['episodes'].insert(0,sample);save(s);return {'id':'demo','duplicate':False}
        if path=='/api/sources':
            u=str(b.get('url','')).strip();k=key(u)
            existing=next((x for x in s['sources'] if x['key']==k),None)
            if existing:return {'duplicate':True,'id':existing['id'],'title':existing['title']}
            text=str(b.get('text','')).strip()
            if text and len(text)<40:raise ValueError('正文至少需要 40 个字；仅有标题无法制作节目。')
            title=str(b.get('title','')).strip() or '等待读取标题'
            m={'id':uuid.uuid4().hex[:12],'key':k,'title':title[:150],'url':u,'text':text[:50000],
               'source':'小红书' if 'xiaohongshu.com' in urlparse(u).hostname else ('微信公众号' if urlparse(u).hostname=='mp.weixin.qq.com' else '网页'),
               'author':'','status':'ready' if text else 'needs_read','created_at':now(),'kind':'article','retrieval':'user_text' if text else 'pending_browser',
               'coverage':{'body':bool(text),'images_read':0,'video_transcribed':False},'coverage_note':'用户补充正文；原文内容未重新核验' if text else '等待取得正文'}
            m['source']=source_name(u)
            if m['source']=='YouTube':m['kind']='video'
            elif m['source']=='Twitter / X':m['kind']='post'
            m['coverage_note']=coverage_note(m)
            s['sources'].insert(0,m);save(s);return {'id':m['id'],'duplicate':False}
        if path=='/api/source/context':
            m=next(x for x in s['sources'] if x['id']==b['id'])
            refs=b.get('references',[])
            if not isinstance(refs,list) or len(refs)>8:raise ValueError('补充来源格式无效。')
            for r in refs:
                key(r['url'])
                if not all(isinstance(r.get(k),str) and r[k].strip() for k in ('title','relationship','text','coverage_note')):raise ValueError('补充来源缺少说明。')
                for c in r.get('cues',[]):
                    if urlparse(r['url']).hostname not in ('www.youtube.com','youtube.com','youtu.be') or not isinstance(c.get('start'),int) or not 0<=c['start']<86400 or not isinstance(c.get('summary'),str) or not c['summary']:raise ValueError('原视频时间点无效。')
            illustration=b.get('illustration')
            if illustration:
                asset=illustration.get('url','')
                if not re.fullmatch(r'/media/sources/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.svg',asset) or not (MEDIA/asset.removeprefix('/media/')).is_file():raise ValueError('图示不存在。')
                m['illustration']=illustration
            m['references']=refs
            if 'reading_note' in b:m['reading_note']=str(b['reading_note'])[:300]
            if b.get('retrieval')=='search_summary':m['retrieval']='search_summary'
            m['coverage_note']=coverage_note(m);save(s);return {'id':m['id'],'references':len(refs)}
        if path=='/api/source/update':
            m=next(x for x in s['sources'] if x['id']==b['id']);text=str(b.get('text','')).strip()
            if len(text)<40:raise ValueError('请补充至少 40 个字的正文或视频转写。')
            m.update(title=str(b.get('title') or m['title'])[:150],text=text[:50000],status='ready',retrieval='user_text',coverage_note='用户补充内容；原文内容未重新核验')
            m['coverage']['body']=True
            if m['kind']=='video':m['coverage']['video_transcribed']=True;m.pop('segments',None)
            save(s);return {'ok':True}
        if path=='/api/jobs':
            import config
            config.check_text()
            if ACTIVE:raise ValueError('有一期节目正在制作，请稍后再试。')
            ids=list(dict.fromkeys(b.get('source_ids',[])))
            if not 1<=len(ids)<=5:raise ValueError('请选择 1 到 5 篇素材。')
            materials=[copy.deepcopy(next(x for x in s['sources'] if x['id']==i)) for i in ids]
            if any(x['status']!='ready' for x in materials):raise ValueError('所选素材还缺少正文，请先补充。')
            if any(x.get('ingest_status')=='reading' for x in materials):raise ValueError('配图或字幕正在读取，请完成后再制作。')
            if any(m.get('coverage',{}).get('images_total',0) and len(m.get('image_notes',[]))<m['coverage']['images_total'] for m in materials):raise ValueError('所选内容还有未整理的配图，请先补齐，避免漏掉关键信息。')
            for m in materials:m['text']=material_text(m);m['coverage_note']=coverage_note(m)
            seconds=int(b.get('seconds',120))
            if seconds not in (60,120,180):raise ValueError('请选择有效的节目时长。')
            ident=uuid.uuid4().hex[:12]
            j={'id':ident,'source_ids':ids,'seconds':seconds,'focus':str(b.get('focus',''))[:300],'status':'drafting','created_at':now(),'error':''}
            folder=DATA/'jobs'/ident;folder.mkdir(parents=True)
            (folder/'request.json').write_text(json.dumps({'job':j,'materials':materials},ensure_ascii=False),encoding='utf-8')
            s['jobs'].insert(0,j);save(s);start_worker(ident,'draft');return {'id':ident}
        if path=='/api/job/draft':
            j=next(x for x in s['jobs'] if x['id']==b['id'])
            if j['status']!='review':raise ValueError('当前节目不能编辑对话稿。')
            j['draft']=valid_draft(b['draft'],j['source_ids']);save(s);return {'ok':True}
        if path=='/api/job/synthesize':
            import config
            config.check_audio()
            if ACTIVE:raise ValueError('有一期节目正在制作，请稍后再试。')
            j=next(x for x in s['jobs'] if x['id']==b['id'])
            if j['status']!='review':raise ValueError('请先完成对话稿。')
            valid_draft(j['draft'],j['source_ids']);(DATA/'jobs'/j['id']/'draft-result.json').write_text(json.dumps(j['draft'],ensure_ascii=False),encoding='utf-8')
            j.update(status='synthesizing',error='');save(s);start_worker(j['id'],'audio');return {'ok':True}
        if path=='/api/job/retry':
            if ACTIVE:raise ValueError('有一期节目正在制作，请稍后再试。')
            j=next(x for x in s['jobs'] if x['id']==b['id'])
            if j['status']!='failed':raise ValueError('仅中断的任务可以重试。')
            stage=j.get('failed_stage','draft');j['status']='drafting' if stage=='draft' else 'synthesizing';j['error']='';save(s);start_worker(j['id'],stage);return {'ok':True}
        if path=='/api/listening':
            e=next(x for x in s['episodes'] if x['id']==b['id']);pos=max(0,min(float(b.get('position',0)),e['duration']))
            e['listen_position']=pos;e['listened']=e.get('listened',False) or pos>=e['duration']*.9;save(s);return {'ok':True}
        raise ValueError('此操作不存在。')

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    initialize()
    print(f'稍后听：http://127.0.0.1:{PORT}',flush=True)
    server.serve_forever()
