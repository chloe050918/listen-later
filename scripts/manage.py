"""Portable launcher; no credentials or workspace state are bundled."""
import argparse,importlib.util,json,os,shutil,socket,subprocess,sys,time,urllib.request,urllib.error,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
if len(sys.argv)>1 and sys.argv[1]!='setup' and PYTHON.exists() and Path(sys.prefix).resolve()!=(ROOT/'.venv').resolve():
    os.execv(str(PYTHON),[str(PYTHON),str(Path(__file__).resolve()),*sys.argv[1:]])
sys.path.insert(0,str(ROOT/'app'))
import paths
MODULES=['requests','bs4','readability','youtube_transcript_api','dotenv','PIL','filelock']

def emit(x):print(json.dumps(x,ensure_ascii=False,indent=2),flush=True)

def api(path,body=None):
    payload=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(paths.BASE+path,data=payload,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        try:msg=json.load(e).get('error','请求失败')
        except Exception:msg='本地接口请求失败'
        raise RuntimeError(msg) from None

def healthy():
    try:
        h=api('/api/health');return h.get('app')=='listen-later' and h.get('version')=='1.0.0' and h.get('instance')==paths.INSTANCE
    except (OSError,ValueError,RuntimeError):return False

def ensure_server():
    if healthy():return
    paths.DATA.mkdir(parents=True,exist_ok=True)
    chosen=None
    ports=[paths.PORT] if os.environ.get('LISTEN_LATER_PORT') else range(paths.PORT,paths.PORT+30)
    for port in ports:
        try:
            with socket.socket() as s:s.bind(('127.0.0.1',port))
            chosen=port;break
        except OSError:continue
    if chosen is None:raise RuntimeError('端口被其他服务占用。设置 LISTEN_LATER_PORT 后重试；不要停止未知服务。')
    paths.PORT=chosen;paths.BASE=f'http://127.0.0.1:{chosen}'
    env={**os.environ,'LISTEN_LATER_PORT':str(chosen),'LISTEN_LATER_DATA':str(paths.DATA)}
    with (paths.DATA/'server.log').open('a') as log:
        proc=subprocess.Popen([sys.executable,str(ROOT/'app/server.py')],env=env,cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(60):
        if healthy():
            (paths.DATA/'runtime.json').write_text(json.dumps({'port':chosen,'pid':proc.pid,'instance':paths.INSTANCE}))
            return
        if proc.poll() is not None:break
        time.sleep(.2)
    raise RuntimeError('服务未启动。运行 doctor 检查依赖；检查数据目录内 server.log。')

def doctor(production=False):
    missing=[m for m in MODULES if importlib.util.find_spec(m) is None]
    env_path=Path(os.environ.get('LISTEN_LATER_ENV',str(paths.DATA/'.env'))).expanduser()
    configured={}
    if not missing:
        import config
        for k in ['ARK_API_KEY','ARK_CHAT_MODEL','VOLC_SPEECH_API_KEY','VOLC_VOICE_HOST_A','VOLC_VOICE_HOST_B']:configured[k]=bool(getattr(config,k))
    audio_tools=bool(shutil.which('ffmpeg')) and bool(shutil.which('ffprobe'))
    ready=sys.version_info>=(3,9) and not missing
    gen=ready and all(configured.values()) and bool(configured) and audio_tools
    if gen:
        import config
        gen=config.VOLC_VOICE_HOST_A!=config.VOLC_VOICE_HOST_B
    emit({'python':sys.version.split()[0],'dependencies_missing':missing,'preview_ready':ready,'generation_configured':gen,'ffmpeg_and_ffprobe':audio_tools,'config_file':str(env_path),'configured_fields':configured,'data_directory':str(paths.DATA),'network_and_provider_access':'未验证；字段存在不代表密钥有效或服务已开通'})
    return 0 if (gen if production else ready) else 2

def wait_job(ident,wait):
    deadline=time.monotonic()+wait
    while True:
        j=next(j for j in api('/api/state')['jobs'] if j['id']==ident)
        if j['status'] not in ('drafting','synthesizing') or time.monotonic()>=deadline:return j
        time.sleep(1)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['setup','doctor','serve','status','demo','import','prepare','finish','verify'])
    p.add_argument('--production',action='store_true');p.add_argument('--input',type=Path)
    p.add_argument('--source-ids',nargs='+');p.add_argument('--seconds',type=int,choices=[60,120,180],default=120)
    p.add_argument('--job');p.add_argument('--review-note');p.add_argument('--wait',type=int,default=0)
    args=p.parse_args()
    if sys.version_info<(3,9):raise RuntimeError('需要 Python 3.9 或以上版本。')
    if args.action=='setup':
        if not PYTHON.exists():venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
        try:
            subprocess.run([str(PYTHON),'-m','pip','install','--disable-pip-version-check','--prefer-binary','--timeout','20','--retries','1','-r',str(ROOT/'requirements.txt'),'-c',str(ROOT/'requirements.lock.txt')],check=True,timeout=900)
        except (subprocess.SubprocessError,OSError):
            raise RuntimeError('Python 依赖安装未完成。请检查 PyPI 网络连接后重新运行 setup；已有环境会保留。')
        paths.DATA.mkdir(parents=True,exist_ok=True)
        envfile=paths.DATA/'.env'
        if not envfile.exists():shutil.copyfile(ROOT/'.env.example',envfile);envfile.chmod(0o600)
        emit({'status':'installed','config_file':str(envfile),'next':'doctor，然后 demo；新内容生成需填写自己的凭证。'});return
    if args.action=='doctor':sys.exit(doctor(args.production))
    missing=[m for m in MODULES if importlib.util.find_spec(m) is None]
    if missing:raise RuntimeError('依赖未安装。先运行 python3 scripts/manage.py setup。缺少：'+', '.join(missing))
    from filelock import FileLock
    paths.DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(paths.DATA/'manage.lock'),timeout=5):
        ensure_server()
        if args.action=='serve':emit({'url':paths.BASE});return
        if args.action=='status':
            s=api('/api/state');emit({'url':paths.BASE,'sources':[{'id':x['id'],'title':x['title'],'status':x['status']} for x in s['sources']],'jobs':[{'id':j['id'],'status':j['status'],'error':j.get('error','')} for j in s['jobs']]});return
        if args.action=='demo':
            sample=json.loads((ROOT/'examples/demo/episode.json').read_text())
            target=paths.MEDIA/'demo';target.mkdir(parents=True,exist_ok=True)
            for f in (ROOT/'examples/demo').iterdir():
                if f.name!='episode.json':shutil.copyfile(f,target/f.name)
            emit(api('/api/demo',{'episode':sample}));emit({'url':paths.BASE+'/#episode/demo','label':'预制示例，未调用模型或语音服务。'});return
        if args.action=='import':
            if not args.input:p.error('import 需要 --input 文件')
            records=json.loads(args.input.read_text());records=records if isinstance(records,list) else [records]
            result=[]
            for r in records:
                if r.get('method')=='browser_use':result.append(api('/api/source/evidence',{'record':r}))
                else:
                    created=api('/api/sources',r);result.append(created)
                    if r.get('references') or r.get('reading_note'):api('/api/source/context',{'id':created['id'],**{k:r[k] for k in ['references','reading_note','retrieval'] if k in r}})
            emit(result);return
        ledger_path=paths.DATA/'schedule.json'
        record=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        if args.action=='prepare':
            s=api('/api/state');pending=next((j for j in s['jobs'] if j['id']==record.get('pending') and j['status']!='complete'),None)
            if pending:j=pending
            else:
                used={i for e in s['episodes'] for i in e['source_ids']}
                selected=args.source_ids or [m['id'] for m in s['sources'] if m['id'] not in used and m['status']=='ready' and m.get('ingest_status')!='reading' and (not m.get('coverage',{}).get('images_total') or len(m.get('image_notes',[]))>=m['coverage']['images_total'])][:3]
                if not selected:emit({'status':'no_new_materials'});return
                j=api('/api/jobs',{'source_ids':selected,'seconds':args.seconds,'focus':'按收藏内容做简报，保留作者与适用范围，不强行串联。'})
                record['pending']=j['id'];ledger_path.write_text(json.dumps(record))
        else:
            if not args.job:p.error('需要 --job ID')
            j=next(j for j in api('/api/state')['jobs'] if j['id']==args.job)
            if args.action=='finish' and j['status']=='review':
                if not args.review_note:p.error('finish 需要 --review-note，记录实际审稿结果')
                (paths.DATA/'jobs'/args.job/'agent-review.json').write_text(json.dumps({'note':args.review_note,'at':time.time()},ensure_ascii=False))
                api('/api/job/synthesize',{'id':args.job})
        j=wait_job(j['id'],min(max(0,args.wait),55))
        if j['status']=='complete':
            e=next(e for e in api('/api/state')['episodes'] if e['id']==j['id'])
            media=paths.MEDIA/e['id']/'episode.mp3'
            subprocess.run(['ffmpeg','-v','error','-i',str(media),'-f','null','-'],check=True,capture_output=True,timeout=60)
            with urllib.request.urlopen(paths.BASE+e['notes_url'],timeout=10) as r:
                if r.status!=200:raise RuntimeError('图文稿无法访问')
            if e['duration']<=0 or len({t['voice'] for t in e['turns']})!=2:raise RuntimeError('音频时长或双音色验证未通过')
            record.pop('pending',None);record['last_completed']=j['id'];ledger_path.write_text(json.dumps(record))
            emit({'status':'complete','id':e['id'],'title':e['title'],'duration':e['duration'],'episode_url':paths.BASE+'/#episode/'+e['id'],'notes_url':paths.BASE+e['notes_url'],'audio_path':str(media)});return
        emit({'id':j['id'],'status':j['status'],'error':j.get('error',''),'request_path':str(paths.DATA/'jobs'/j['id']/'request.json'),'draft_path':str(paths.DATA/'jobs'/j['id']/'draft-result.json'),'url':paths.BASE+'/#job/'+j['id']})
        if j['status']=='failed':sys.exit(1)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:sys.exit(130)
    except Exception as e:
        # Provider responses are never printed here; API errors are sanitized by the app.
        print(str(e) if isinstance(e,RuntimeError) else '操作未完成，请运行 doctor 并检查本机任务记录。',file=sys.stderr);sys.exit(1)
