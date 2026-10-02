#!/usr/bin/env python3
"""Small DOMjudge 9 + LM Studio runner. Python 3.10+, standard library only.

No generated program is executed by this process; DOMjudge handles judging.
The default protocol returns verdicts only, never secret test data.
"""
import argparse, base64, csv, getpass, hashlib, io, json, os, re, statistics
import sys, time, zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

class HarnessError(Exception): pass
class ApiError(HarnessError):
    def __init__(self,message,status=None):super().__init__(message);self.status=status

def now(): return datetime.now(timezone.utc).isoformat()
def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
def sha(value):return hashlib.sha256(value.encode()).hexdigest()

class Client:
    def __init__(self,base,username=None,password=None,key=None,timeout=60):
        self.base=base.rstrip('/');self.timeout=timeout;self.headers={'Accept':'application/json'}
        if username is not None:
            token=base64.b64encode(f'{username}:{password}'.encode()).decode()
            self.headers['Authorization']='Basic '+token
        if key:self.headers['Authorization']='Bearer '+key
    def call(self,method,path,payload=None,query=None):
        url=self.base+'/'+path.lstrip('/')
        if query:url+='?'+urlencode(query)
        headers=dict(self.headers);data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers['Content-Type']='application/json'
        req=Request(url,data=data,headers=headers,method=method)
        try:
            with urlopen(req,timeout=self.timeout) as response:
                raw=response.read()
        except HTTPError as exc:
            # No credentials or raw server bodies enter console/error logs.
            raise ApiError(f'{method} {path}: HTTP {exc.code}. Check credentials, IDs, contest window, and API base.',exc.code) from None
        except (URLError,TimeoutError,OSError):
            raise ApiError(f'{method} {path}: connection failed or timed out.') from None
        try:return json.loads(raw)
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise ApiError(f'{method} {path}: expected JSON; verify the API URL.') from None

def identifier(value):return quote(str(value),safe='')
def contest_path(cid,tail=''):return 'contests/'+identifier(cid)+(('/'+tail) if tail else '')
def dom_client(config,model,interactive=True):
    user=os.environ.get(model.get('username_env','DOMJUDGE_USER')) or model.get('username')
    pwd=os.environ.get(model.get('password_env','DOMJUDGE_PASSWORD'))
    if not user:raise HarnessError('Set a team username in config.json or DOMJUDGE_USER.')
    if pwd is None:
        if not interactive or not sys.stdin.isatty():raise HarnessError('Set DOMJUDGE_PASSWORD, or run in a terminal to enter it privately.')
        pwd=getpass.getpass(f'DOMjudge password for {user}: ')
    return Client(config['domjudge_api'],user,pwd,timeout=config.get('api_timeout_s',60))
def lm_client(config):return Client(config['lmstudio_api'],key=os.environ.get('LMSTUDIO_API_KEY'),timeout=config.get('generation_timeout_s',600))
def load_config(path):
    file=Path(path).resolve();cfg=json.loads(file.read_text(encoding='utf-8'));cfg['_root']=str(file.parent)
    for k in ['domjudge_api','lmstudio_api']:
        if urlsplit(cfg[k]).scheme not in ['http','https']:raise HarnessError(k+' must be an HTTP(S) URL.')
    if not 1<=cfg.get('attempts',3)<=10:raise HarnessError('attempts must be between 1 and 10.')
    if cfg.get('repetitions',1)<1:raise HarnessError('repetitions must be positive.')
    return cfg
def get_model(cfg,label):
    models=[m for m in cfg['models'] if m['label']==label]
    if len(models)!=1:raise HarnessError('Unknown or duplicated model label: '+label)
    return models[0]
def require_ids(cfg):
    if not cfg.get('contest_id'):raise HarnessError('Set contest_id from doctor output in config.json.')
    if not cfg.get('language_id'):raise HarnessError('Set the C++ language_id from doctor output in config.json.')

def doctor(cfg,label):
    model=get_model(cfg,label);dj=dom_client(cfg,model)
    for tail in ['contests','languages']:
        try:print(tail+':\n'+json.dumps(dj.call('GET',tail),indent=2))
        except ApiError as exc:print(str(exc))
    if cfg.get('contest_id'):
        for tail in ['account','problems']:
            try:print(tail+':\n'+json.dumps(dj.call('GET',contest_path(cfg['contest_id'],tail)),indent=2))
            except ApiError as exc:print(str(exc))
    try:print('LM Studio model IDs:\n'+json.dumps(lm_client(cfg).call('GET','models'),indent=2))
    except ApiError as exc:print(str(exc))

def validate_problem(dj,cfg,problem):
    available=dj.call('GET',contest_path(cfg['contest_id'],'problems'))
    if not any(str(p['id'])==str(problem['judge_id']) for p in available):
        raise HarnessError('Problem ID not visible to this team: '+str(problem['judge_id']))
    language=dj.call('GET','languages/'+identifier(cfg['language_id']))
    return {'problem':next(p for p in available if str(p['id'])==str(problem['judge_id'])), 'language':language}

def extract_cpp(content):
    if not isinstance(content,str) or not content.strip():raise HarnessError('Empty model response.')
    content=re.sub(r'<think>.*?</think>','',content,flags=re.S).strip()
    blocks=re.findall(r'```([^\n]*)\n(.*?)```',content,flags=re.S)
    candidates=[body.strip() for language,body in blocks if language.strip().lower() in ['cpp','c++','cxx','cc','']]
    if len(candidates)>1:raise HarnessError('Multiple C++ blocks; source extraction is ambiguous.')
    source=candidates[0] if candidates else content
    if re.search(r'\bmain\s*\(',source) is None:raise HarnessError('Response does not contain a complete program with main().')
    return source.rstrip()+'\n'

def submission_payload(problem,language,source):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('main.cpp',source)
    return {'problem':str(problem),'language':str(language),
            'files':[{'mime':'application/zip','data':base64.b64encode(stream.getvalue()).decode()}]}

def final_judgement(items,submission_id):
    matches=[j for j in items if str(j.get('submission_id'))==str(submission_id) and j.get('valid',True)]
    if not matches:return None
    newest=max(matches,key=lambda j:int(j['id']))
    return newest if newest.get('end_time') and newest.get('judgement_type_id') else None

def wait_for_judgement(dj,cfg,submission_id):
    start=time.monotonic()
    while True:
        result=final_judgement(dj.call('GET',contest_path(cfg['contest_id'],'judgements')),submission_id)
        if result:return result,time.monotonic()-start
        if time.monotonic()-start>=cfg.get('judge_timeout_s',600):
            raise HarnessError('Judging timed out. This attempt stays pending; rerun to poll the same submission.')
        time.sleep(cfg.get('poll_interval_s',2))

def save_state(folder,state):atomic_json(folder/'state.json',state)
def protocol_config(cfg,model,problem,prompt):
    return {k:cfg.get(k) for k in ['domjudge_api','lmstudio_api','contest_id','language_id','attempts','repetitions','temperature','top_p','max_tokens','seed']}

def run_job(cfg,model,problem,repeat,dj,lm,metadata):
    root=Path(cfg['_root']);prompt=(root/problem['statement']).read_text(encoding='utf-8')
    instruction=('Solve this competitive programming problem. Return exactly one complete C++17 program '
                 'inside a single ```cpp code block. Read standard input and write standard output. '
                 'Do not access files or a network. The statement uses LaTeX notation.\n\n')
    limits=metadata['problem']
    initial=instruction+'DOMjudge problem configuration:\n'+json.dumps({k:limits[k] for k in ['time_limit','memory_limit'] if k in limits})+'\n\n'+prompt
    fingerprint=sha(json.dumps({'settings':protocol_config(cfg,model,problem,prompt),
                               'model':{k:v for k,v in model.items() if 'password' not in k},
                               'problem':problem,'prompt':initial,'metadata':metadata},sort_keys=True))
    folder=root/cfg.get('output_directory','results')/model['label']/problem['slug']/f'repeat-{repeat:02d}'
    folder.mkdir(parents=True,exist_ok=True);state_path=folder/'state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text(encoding='utf-8'))
        if state['fingerprint']!=fingerprint:raise HarnessError('Configuration changed for an existing run. Use a new output_directory.')
    else:
        state={'fingerprint':fingerprint,'model':model['label'],'model_id':model['identifier'],
               'problem':problem['slug'],'judge_problem_id':str(problem['judge_id']),
               'repeat':repeat,'status':'RUNNING','created_at':now(),'metadata':metadata,
               'settings':protocol_config(cfg,model,problem,prompt),'model_notes':model.get('notes',''),
               'messages':[{'role':'user','content':initial}],'attempts':[]}
        save_state(folder,state)
    if state['status'] in ['ACCEPTED','EXHAUSTED']:return
    while len(state['attempts'])<cfg.get('attempts',3) or (state['attempts'] and state['attempts'][-1]['status']!='DONE'):
        if state['attempts'] and state['attempts'][-1]['status']!='DONE':
            attempt=state['attempts'][-1]
        else:
            attempt={'number':len(state['attempts'])+1,'status':'GENERATING','created_at':now()}
            state['attempts'].append(attempt);save_state(folder,state)
        number=attempt['number'];prefix=f'attempt-{number:02d}'
        if attempt['status']=='SUBMITTING':
            raise HarnessError('Submission outcome is unknown. Inspect DOMjudge, then use attach-submission; automatic resubmission is disabled.')
        if attempt['status']=='GENERATING':
            payload={'model':model['identifier'],'messages':state['messages'],
                     'temperature':cfg.get('temperature',0.2),'top_p':cfg.get('top_p',0.95),
                     'max_tokens':cfg.get('max_tokens',4096),'stream':False,
                     'seed':cfg.get('seed',2202)+repeat-1}
            atomic_json(folder/(prefix+'-request.json'),payload)
            started=time.monotonic();response=lm.call('POST','chat/completions',payload)
            attempt['generation_s']=time.monotonic()-started
            atomic_json(folder/(prefix+'-response.json'),response)
            content=''
            try:
                choice=response['choices'][0];content=choice['message'].get('content','')
                attempt['usage']=response.get('usage',{});attempt['finish_reason']=choice.get('finish_reason')
                if attempt['finish_reason']=='length':raise HarnessError('Model reached the output-token limit.')
                code=extract_cpp(content)
            except (KeyError,IndexError,TypeError,HarnessError) as exc:
                attempt.update(status='DONE',verdict='GENERATION_FORMAT_ERROR',error=str(exc),completed_at=now())
                correction='Your last response was incomplete or did not contain a single complete C++17 program. Return the full program in one cpp code block.'
                if isinstance(content,str) and content:
                    state['messages'].append({'role':'assistant','content':content})
                    state['messages'].append({'role':'user','content':correction})
                else:
                    state['messages'][-1]['content']+='\n\n'+correction
                save_state(folder,state);continue
            (folder/(prefix+'.cpp')).write_text(code,encoding='utf-8')
            attempt.update(status='GENERATED',source_sha256=sha(code))
            state['messages'].append({'role':'assistant','content':content})
            save_state(folder,state)
        if attempt['status']=='GENERATED':
            code=(folder/(prefix+'.cpp')).read_text(encoding='utf-8')
            attempt.update(status='SUBMITTING',submit_started_at=now());save_state(folder,state)
            try:
                result=dj.call('POST',contest_path(cfg['contest_id'],'submissions'),
                               submission_payload(problem['judge_id'],cfg['language_id'],code))
            except ApiError as exc:
                if exc.status in [400,401,403,404,413,422]:
                    attempt['status']='GENERATED';save_state(folder,state)
                raise
            if not result.get('id'):raise HarnessError('Submission response has no ID; inspect DOMjudge before retrying.')
            attempt.update(status='PENDING',submission_id=str(result['id']),submission_response=result)
            save_state(folder,state)
        if attempt['status']=='PENDING':
            judgement,wait_s=wait_for_judgement(dj,cfg,attempt['submission_id'])
            verdict=judgement['judgement_type_id']
            attempt.update(status='DONE',verdict=verdict,judgement=judgement,
                           judge_poll_wait_s=attempt.get('judge_poll_wait_s',0)+wait_s,
                           judge_max_runtime_for_verdict_s=judgement.get('max_run_time'),
                           memory_mb=None,completed_at=now())
            if verdict=='AC':state['status']='ACCEPTED'
            else:state['messages'].append({'role':'user','content':f'DOMjudge verdict: {verdict}. Repair your previous solution. Return exactly one complete C++17 program in a single cpp code block. No hidden test information is available.'})
            save_state(folder,state)
            print(f'{model["label"]} / {problem["slug"]} / repetition {repeat} / attempt {number}: {verdict}',flush=True)
            if state['status']=='ACCEPTED':break
    if state['status']!='ACCEPTED':state['status']='EXHAUSTED'
    state['completed_at']=now();save_state(folder,state)

def export(cfg):
    out=Path(cfg['_root'])/cfg.get('output_directory','results');out.mkdir(parents=True,exist_ok=True)
    runs=[];attempts=[]
    for file in sorted(out.glob('*/*/repeat-*/state.json')):
        s=json.loads(file.read_text(encoding='utf-8'));done=[a for a in s['attempts'] if a['status']=='DONE']
        complete=s['status'] in ['ACCEPTED','EXHAUSTED']
        accepted=int(s['status']=='ACCEPTED') if complete else None
        gen=sum(a.get('generation_s',0) for a in done)
        waits=sum(a.get('judge_poll_wait_s',0) for a in done)
        runs.append(dict(model=s['model'],model_id=s['model_id'],problem=s['problem'],repeat=s['repeat'],
                         status=s['status'],accepted=accepted,first_accepted=int(bool(done) and done[0].get('verdict')=='AC') if complete else None,
                         attempts_used=len(s['attempts']),attempts_to_accept=len(done) if accepted else None,
                         observed_generation_s=gen,observed_poll_wait_s=waits,
                         solved_generation_s=gen if accepted else None))
        for a in s['attempts']:
            attempts.append(dict(model=s['model'],model_id=s['model_id'],problem=s['problem'],repeat=s['repeat'],
                attempt=a['number'],status=a['status'],submission_id=a.get('submission_id'),verdict=a.get('verdict'),
                generation_s=a.get('generation_s'),judge_poll_wait_s=a.get('judge_poll_wait_s'),
                judge_max_runtime_for_verdict_s=a.get('judge_max_runtime_for_verdict_s'),memory_mb=a.get('memory_mb'),
                prompt_tokens=a.get('usage',{}).get('prompt_tokens'),completion_tokens=a.get('usage',{}).get('completion_tokens')))
    for name,rows in [('runs.csv',runs),('attempts.csv',attempts)]:
        if rows:
            with (out/name).open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary=[]
    for model in sorted({m['label'] for m in cfg['models']} | {r['model'] for r in runs}):
        rows=[r for r in runs if r['model']==model];complete=[r for r in rows if r['accepted'] is not None]
        n=len(complete);k=sum(r['accepted'] for r in complete);first=sum(r['first_accepted'] for r in complete)
        configured=len(cfg['problems'])*cfg.get('repetitions',1)
        summary.append(dict(model=model,configured_runs=configured,started_runs=len(rows),completed_runs=n,incomplete_started_runs=len(rows)-n,
            accepted=k,first_accepted=first,acceptance_rate=k/n if n else None,
            first_acceptance_rate=first/n if n else None,
            median_observed_generation_s=statistics.median(r['observed_generation_s'] for r in complete) if n else None,
            note='Descriptive run-level rates. Repetitions share problems; do not treat them as independent problems.'))
    atomic_json(out/'summary.json',summary)
    print('Results exported to '+str(out))

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',default='config.json')
    sub=ap.add_subparsers(dest='command',required=True)
    doctor_p=sub.add_parser('doctor');doctor_p.add_argument('--model',default='qwen')
    run=sub.add_parser('run');run.add_argument('--model',required=True);run.add_argument('--problem');run.add_argument('--repeat',type=int)
    smoke=sub.add_parser('submit-file');smoke.add_argument('--model',default='qwen');smoke.add_argument('--problem',required=True);smoke.add_argument('--file',required=True)
    sub.add_parser('export')
    attach=sub.add_parser('attach-submission');attach.add_argument('--state',required=True);attach.add_argument('--submission-id',required=True)
    attach.add_argument('--source-file',required=True,help='Source downloaded from that submission in the DOMjudge jury UI')
    args=ap.parse_args(argv);cfg=load_config(args.config)
    if args.command=='export':export(cfg);return
    if args.command=='doctor':doctor(cfg,args.model);return
    require_ids(cfg)
    if args.command=='attach-submission':
        f=Path(args.state);s=json.loads(f.read_text(encoding='utf-8'));a=s['attempts'][-1]
        if a['status']!='SUBMITTING':raise HarnessError('Only an ambiguous SUBMITTING attempt can be attached.')
        model=get_model(cfg,s['model']);dj=dom_client(cfg,model)
        response=dj.call('GET',contest_path(cfg['contest_id'],'submissions/'+identifier(args.submission_id)))
        if str(response.get('problem_id'))!=s['judge_problem_id']:raise HarnessError('Submission belongs to a different problem.')
        account=dj.call('GET',contest_path(cfg['contest_id'],'account'))
        if not account.get('team_id') or str(account['team_id'])!=str(response.get('team_id')):
            raise HarnessError('Submission belongs to a different team.')
        if str(response.get('language_id'))!=str(cfg['language_id']):raise HarnessError('Submission uses a different language.')
        if Path(args.source_file).read_text(encoding='utf-8')!=(f.parent/f'attempt-{a["number"]:02d}.cpp').read_text(encoding='utf-8'):
            raise HarnessError('Submission source differs from the pending attempt; do not attach it.')
        a.update(status='PENDING',submission_id=str(response['id']));atomic_json(f,s);return
    model=get_model(cfg,args.model);dj=dom_client(cfg,model)
    if args.command=='submit-file':
        candidates=[p for p in cfg['problems'] if p['slug']==args.problem]
        if len(candidates)!=1:raise HarnessError('Unknown configured problem slug: '+args.problem)
        problem=candidates[0];validate_problem(dj,cfg,problem)
        source=Path(args.file).read_text(encoding='utf-8')
        result=dj.call('POST',contest_path(cfg['contest_id'],'submissions'),submission_payload(problem['judge_id'],cfg['language_id'],source))
        print('Submission ID:',result['id']);judgement,_=wait_for_judgement(dj,cfg,str(result['id']))
        print(json.dumps(judgement,indent=2));return
    if not model.get('identifier') or model['identifier'].startswith('REPLACE_'):
        raise HarnessError('Set identifier to the exact model ID returned by LM Studio in doctor output.')
    lm=lm_client(cfg);visible=lm.call('GET','models').get('data',[])
    if not any(m.get('id')==model['identifier'] for m in visible):raise HarnessError('Configured model ID is not visible in LM Studio.')
    problems=[p for p in cfg['problems'] if not args.problem or p['slug']==args.problem]
    if not problems:raise HarnessError('No matching configured problem.')
    repetitions=[args.repeat] if args.repeat else list(range(1,cfg.get('repetitions',1)+1))
    if any(n<1 or n>cfg.get('repetitions',1) for n in repetitions):raise HarnessError('Repetition is outside configured range.')
    try:
        for p in problems:
            metadata=validate_problem(dj,cfg,p)
            for repeat in repetitions:run_job(cfg,model,p,repeat,dj,lm,metadata)
    finally:export(cfg)

if __name__=='__main__':
    try:main()
    except (HarnessError,ValueError,OSError) as exc:
        print('Stopped:',str(exc),file=sys.stderr);sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command to resume persisted runs.',file=sys.stderr);sys.exit(130)
