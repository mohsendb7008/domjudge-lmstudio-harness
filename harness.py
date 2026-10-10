#!/usr/bin/env python3
"""Resumable DOMjudge open contest runner. Python 3.10+, standard library only.

No generated program is executed by this process; DOMjudge handles judging.
The default protocol returns verdicts only, never secret test data.
"""
import argparse, base64, csv, getpass, hashlib, io, json, os, re, statistics
import sys, time, zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from providers import (PROVIDERS, provider_name, generation_payload,
                       response_content, generation_call)

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
            raise ApiError(f'{method} {path}: HTTP {exc.code}. Check API credentials, IDs, and service configuration.',exc.code) from None
        except (URLError,TimeoutError,OSError):
            raise ApiError(f'{method} {path}: connection failed or timed out.') from None
        try:return json.loads(raw)
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise ApiError(f'{method} {path}: expected JSON; verify the API URL.') from None

def identifier(value):return quote(str(value),safe='')
def contest_path(cid,tail=''):return 'contests/'+identifier(cid)+(('/'+tail) if tail else '')
def dom_client(config,model,interactive=True):
    user=os.environ.get(model.get('username_env') or 'DOMJUDGE_USER') or model.get('username')
    pwd=os.environ.get(model.get('password_env') or 'DOMJUDGE_PASSWORD')
    if not user:raise HarnessError('Set a team username in config.json or DOMJUDGE_USER.')
    if pwd is None:
        if not interactive or not sys.stdin.isatty():raise HarnessError('Set DOMJUDGE_PASSWORD, or run in a terminal to enter it privately.')
        pwd=getpass.getpass(f'DOMjudge password for {user}: ')
    return Client(config['domjudge_api'],user,pwd,timeout=config.get('api_timeout_s',60))
def lm_client(config):return Client(config['lmstudio_api'],key=os.environ.get('LMSTUDIO_API_KEY'),timeout=config.get('generation_timeout_s',600))

def model_client(cfg,model):
    provider=provider_name(model)
    defaults={'lmstudio':('lmstudio_api','http://localhost:1234/v1','LMSTUDIO_API_KEY'),
              'openai':('openai_api','https://api.openai.com/v1','OPENAI_API_KEY'),
              'anthropic':('anthropic_api','https://api.anthropic.com/v1','ANTHROPIC_API_KEY')}
    setting,base,env=defaults[provider]
    key=os.environ.get(model.get('api_key_env') or env)
    if provider!='lmstudio' and not key:raise HarnessError('Set '+(model.get('api_key_env') or env)+' before running '+model['label']+'.')
    client=Client(model.get('api_base') or cfg.get(setting,base),key=key if provider!='anthropic' else None,
                  timeout=cfg.get('generation_timeout_s',600))
    if provider=='anthropic':client.headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
    return client

@contextmanager
def model_session(cfg,model):
    client=model_client(cfg,model);native=None;instance=None
    if provider_name(model)=='lmstudio':
        if cfg.get('auto_load_models',False):
            native=Client(cfg.get('lmstudio_management_api','http://localhost:1234/api/v1'),
                          key=os.environ.get(model.get('api_key_env') or 'LMSTUDIO_API_KEY'),
                          timeout=cfg.get('generation_timeout_s',600))
            payload={'model':model['identifier']}
            if model.get('context_length'):payload['context_length']=model['context_length']
            result=native.call('POST','models/load',payload)
            instance=result.get('instance_id')
            if not instance:raise HarnessError('LM Studio load response has no instance_id.')
            client.model_id=instance
        else:
            visible=client.call('GET','models').get('data',[])
            if not any(m.get('id')==model['identifier'] for m in visible):
                raise HarnessError('Configured model ID is not visible in LM Studio; load it or enable auto_load_models.')
    try:yield client
    finally:
        if native and instance:
            try:native.call('POST','models/unload',{'instance_id':instance})
            except ApiError as exc:print('Could not unload LM Studio model: '+str(exc),file=sys.stderr)

def load_config(path):
    file=Path(path).resolve();cfg=json.loads(file.read_text(encoding='utf-8'));cfg['_root']=str(file.parent)
    for k in ['domjudge_api','lmstudio_api','openai_api','anthropic_api','lmstudio_management_api']:
        if k in cfg and urlsplit(cfg[k]).scheme not in ['http','https']:raise HarnessError(k+' must be an HTTP(S) URL.')
    if not cfg.get('domjudge_api'):raise HarnessError('Set domjudge_api.')
    for k,default,lower,upper in [('attempts',10,1,10),('repetitions',2,1,2),('generation_retries',3,0,10)]:
        value=cfg.get(k,default)
        if type(value)!=int or not lower<=value<=upper:raise HarnessError(f'{k} must be an integer between {lower} and {upper}.')
    if cfg.get('problem_selection','model') not in ['model','easiest','configured']:
        raise HarnessError('problem_selection must be model, easiest, or configured.')
    for collection,key in [('models','label'),('problems','slug')]:
        seen=set()
        for item in cfg.get(collection,[]):
            name=item.get(key,'')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name) or name in seen:
                raise HarnessError('Invalid or duplicated '+key+': '+str(name))
            seen.add(name)
        if not seen:raise HarnessError('Configure at least one '+collection+' entry.')
    for model in cfg['models']:
        if provider_name(model) not in PROVIDERS:raise HarnessError('Unknown provider for '+model['label'])
        if 'enabled' in model and type(model['enabled'])!=bool:raise HarnessError('enabled must be true or false.')
        if 'api_key' in model:raise HarnessError('Use api_key_env; never put API keys in config.')
        if model.get('api_base') and urlsplit(model['api_base']).scheme not in ['http','https']:
            raise HarnessError('api_base must be an HTTP(S) URL.')
    if not isinstance(cfg.get('hidden_hints',{}),dict):raise HarnessError('hidden_hints must map problem slugs to hint text.')
    for hint in list(cfg.get('hidden_hints',{}).values())+[p.get('hidden_hint','') for p in cfg['problems']]:
        if not isinstance(hint,str):raise HarnessError('Hidden hints must be strings.')
    if set(cfg.get('hidden_hints',{}))-{p['slug'] for p in cfg['problems']}:
        raise HarnessError('hidden_hints contains an unknown problem slug.')
    for p in cfg['problems']:
        if p.get('difficulty') is not None and (type(p['difficulty']) not in (int,float) or not 0<=p['difficulty']<float('inf')):
            raise HarnessError('difficulty must be a nonnegative finite number; lower means easier.')
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
    try:print(provider_name(model)+' model IDs:\n'+json.dumps(model_client(cfg,model).call('GET','models'),indent=2))
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
    defaults={'attempts':10,'repetitions':2}
    return {k:cfg.get(k,defaults.get(k)) for k in ['domjudge_api','lmstudio_api','openai_api','anthropic_api','contest_id','language_id','attempts','repetitions','temperature','top_p','max_tokens','seed','problem_selection']}

def hidden_hint(cfg,problem,repeat):
    return (problem.get('hidden_hint') or cfg.get('hidden_hints',{}).get(problem['slug'],'')) if repeat==2 else ''

def generation_messages(state):
    # Keep the full audit history on disk, but send only the latest repair exchange.
    # Ten large responses otherwise exceed the local model's context window.
    messages=state['messages']
    return messages if len(messages)<=3 else [messages[0],*messages[-2:]]

def run_job(cfg,model,problem,repeat,dj,lm,metadata):
    root=Path(cfg['_root']);prompt=(root/problem['statement']).read_text(encoding='utf-8')
    instruction=('Solve this competitive programming problem. Return exactly one complete C++17 program '
                 'inside a single ```cpp code block. Read standard input and write standard output. '
                 'Do not access files or a network. The statement uses LaTeX notation.\n\n')
    limits=metadata['problem']
    initial=instruction+'DOMjudge problem configuration:\n'+json.dumps({k:limits[k] for k in ['time_limit','memory_limit'] if k in limits})+'\n\n'+prompt
    hint=hidden_hint(cfg,problem,repeat)
    if hint:initial+='\n\nRound 2 hint:\n'+hint
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
               'repeat':repeat,'provider':provider_name(model),'hint_used':bool(hint),
               'status':'RUNNING','created_at':now(),'metadata':metadata,
               'settings':protocol_config(cfg,model,problem,prompt),'model_notes':model.get('notes',''),
               'messages':[{'role':'user','content':initial}],'attempts':[]}
        save_state(folder,state)
    if state['status'] in ['ACCEPTED','EXHAUSTED']:return
    while len(state['attempts'])<cfg.get('attempts',10) or (state['attempts'] and state['attempts'][-1]['status']!='DONE'):
        if state['attempts'] and state['attempts'][-1]['status']!='DONE':
            attempt=state['attempts'][-1]
        else:
            attempt={'number':len(state['attempts'])+1,'status':'GENERATING','created_at':now()}
            state['attempts'].append(attempt);save_state(folder,state)
        number=attempt['number'];prefix=f'attempt-{number:02d}'
        if attempt['status']=='SUBMITTING':
            raise HarnessError('Submission outcome is unknown. Inspect DOMjudge, then use attach-submission; automatic resubmission is disabled.')
        if attempt['status']=='GENERATING':
            payload=generation_payload(cfg,model,generation_messages(state),repeat,getattr(lm,'model_id',None))
            atomic_json(folder/(prefix+'-request.json'),payload)
            started=time.monotonic();response=generation_call(lm,model,payload,cfg,ApiError)
            attempt['generation_s']=time.monotonic()-started
            atomic_json(folder/(prefix+'-response.json'),response)
            content=''
            try:
                content,attempt['usage'],attempt['finish_reason']=response_content(response,model)
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

def job_folder(cfg,model,problem,repeat):
    return Path(cfg['_root'])/cfg.get('output_directory','results')/model['label']/problem['slug']/f'repeat-{repeat:02d}'

def read_job(cfg,model,problem,repeat):
    path=job_folder(cfg,model,problem,repeat)/'state.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def is_solved(cfg,model,problem):
    return any((read_job(cfg,model,problem,n) or {}).get('status')=='ACCEPTED'
               for n in range(1,cfg.get('repetitions',2)+1))

def easiest_problem(problems):
    # Stable config order breaks ties and is the fallback when difficulty is unknown.
    return min(problems,key=lambda p:p.get('difficulty') if p.get('difficulty') is not None else float('inf'))

def select_problem(cfg,model,problems,repeat,lm,folder,index):
    policy=cfg.get('problem_selection','model')
    if policy=='configured':return problems[0]
    if policy=='easiest':return easiest_problem(problems)
    # Construct a public-only view explicitly. Hints/references/test metadata never enter selection.
    public=[{'slug':p['slug'],'name':p.get('name',p['slug']),'difficulty':p.get('difficulty'),
             'statement':(Path(cfg['_root'])/p['statement']).read_text(encoding='utf-8')} for p in problems]
    instruction=('Choose the easiest problem for you to solve from these unsolved candidates. '
                 'Lower numeric difficulty means easier; null means unknown. '
                 'Return ONLY a JSON object with one key, "problem", containing an exact candidate slug.\n\n')
    payload=generation_payload(cfg,model,[{'role':'user','content':instruction+json.dumps(public,ensure_ascii=False)}],
                               repeat,getattr(lm,'model_id',None),selection=True)
    atomic_json(folder/f'selection-{index:03d}-request.json',payload)
    response=generation_call(lm,model,payload,cfg,ApiError)
    atomic_json(folder/f'selection-{index:03d}-response.json',response)
    try:
        content,_,reason=response_content(response,model)
        if reason=='length':raise ValueError()
        content=re.sub(r'<think>.*?</think>','',content,flags=re.S).strip()
        content=re.sub(r'^```(?:json)?\s*|\s*```$','',content).strip()
        slug=json.loads(content)['problem']
        return next(p for p in problems if p['slug']==slug)
    except (KeyError,IndexError,TypeError,ValueError,StopIteration):
        print('Invalid problem selection; using configured difficulty/order fallback.',flush=True)
        return easiest_problem(problems)

def run_contest(cfg,models,problems,repetitions):
    out=Path(cfg['_root'])/cfg.get('output_directory','results');out.mkdir(parents=True,exist_ok=True)
    # Resolve credentials and validate every selected team before a long unattended run.
    clients={};metadata={}
    for model in models:
        if not isinstance(model.get('identifier'),str) or not model['identifier'] or model['identifier'].startswith('REPLACE_'):
            raise HarnessError('Set the exact provider model identifier for '+model['label']+'.')
        clients[model['label']]=dom_client(cfg,model)
        for p in problems:
            metadata[(model['label'],p['slug'])]=validate_problem(clients[model['label']],cfg,p)
        model_client(cfg,model)  # Check cloud credentials before any generation.
    if repetitions[0]==2:
        for model in models:
            if any((read_job(cfg,model,p,1) or {}).get('status') not in ['ACCEPTED','EXHAUSTED'] for p in problems):
                raise HarnessError('Finish round 1 before selecting --repeat 2; run without --repeat to do both.')
    manifest_path=out/'contest.json'
    settings={k:v for k,v in cfg.items() if k not in ['_root','output_directory']}
    fingerprint=sha(json.dumps({'config':settings,
        'prompts':{p['slug']:sha((Path(cfg['_root'])/p['statement']).read_text(encoding='utf-8')) for p in cfg['problems']}},sort_keys=True))
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['config_fingerprint']!=fingerprint:
            raise HarnessError('Configuration changed for this contest (settings or prompts). Use a new output_directory.')
    else:
        manifest={'config_fingerprint':fingerprint,'created_at':now(),'metadata_fingerprints':{},'jobs':[]}
    for key,value in metadata.items():
        name='/'.join(key);digest=sha(json.dumps(value,sort_keys=True))
        if name in manifest['metadata_fingerprints'] and manifest['metadata_fingerprints'][name]!=digest:
            raise HarnessError('Configuration changed: judge metadata differs. Use a new output_directory.')
        manifest['metadata_fingerprints'][name]=digest
    atomic_json(manifest_path,manifest)
    for repeat in repetitions:
        for model in models:
            candidates=[p for p in problems if not is_solved(cfg,model,p)
                        and (read_job(cfg,model,p,repeat) or {}).get('status')!='EXHAUSTED']
            if not candidates:continue
            print(f'Round {repeat}/{cfg.get("repetitions",2)}: {model["label"]}, {len(candidates)} unsolved problems.',flush=True)
            with model_session(cfg,model) as lm:
                while candidates:
                    # Resume a persisted job before asking the model to choose again.
                    pending=[p for p in candidates if read_job(cfg,model,p,repeat)]
                    scheduled=[j for j in manifest['jobs'] if j['model']==model['label'] and j['repeat']==repeat
                               and any(p['slug']==j['problem'] for p in candidates)]
                    if pending:problem=pending[0]
                    elif scheduled:problem=next(p for p in candidates if p['slug']==scheduled[0]['problem'])
                    else:
                        folder=out/model['label']/f'round-{repeat:02d}'
                        index=1+sum(j['model']==model['label'] and j['repeat']==repeat for j in manifest['jobs'])
                        problem=select_problem(cfg,model,candidates,repeat,lm,folder,index)
                        manifest['jobs'].append({'model':model['label'],'repeat':repeat,'problem':problem['slug'],'selected_at':now()})
                        atomic_json(manifest_path,manifest)
                    print(f'{model["label"]} chose {problem["slug"]} in round {repeat}.',flush=True)
                    run_job(cfg,model,problem,repeat,clients[model['label']],lm,metadata[(model['label'],problem['slug'])])
                    candidates=[p for p in candidates if p['slug']!=problem['slug']]
    manifest['updated_at']=now();atomic_json(manifest_path,manifest)

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
                         provider=s.get('provider','lmstudio'),hint_used=s.get('hint_used',False),
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
        configured=len(cfg['problems'])*cfg.get('repetitions',2)
        summary.append(dict(model=model,configured_runs=configured,started_runs=len(rows),completed_runs=n,incomplete_started_runs=len(rows)-n,
            accepted=k,first_accepted=first,acceptance_rate=k/n if n else None,
            first_acceptance_rate=first/n if n else None,
            median_observed_generation_s=statistics.median(r['observed_generation_s'] for r in complete) if n else None,
            note='Descriptive run-level rates. Repetitions share problems; do not treat them as independent problems.'))
    atomic_json(out/'summary.json',summary)
    scoreboard=[]
    for model in cfg['models']:
        rows=[r for r in runs if r['model']==model['label']]
        solved=sorted({r['problem'] for r in rows if r['accepted']})
        unassisted=sorted({r['problem'] for r in rows if r['accepted'] and not r['hint_used']})
        unsolved=[p['slug'] for p in cfg['problems'] if p['slug'] not in solved]
        exhausted=[slug for slug in unsolved if all(any(r['problem']==slug and r['repeat']==n and r['status']=='EXHAUSTED' for r in rows)
                    for n in range(1,cfg.get('repetitions',2)+1))]
        scoreboard.append(dict(model=model['label'],enabled=model.get('enabled',True),solved=len(solved),
            total_problems=len(cfg['problems']),solved_problems=solved,solved_without_hint=unassisted,
            unsolved_problems=unsolved,exhausted_problems=exhausted,
            contest_complete=len(solved)+len(exhausted)==len(cfg['problems']),
            attempts_used=sum(r['attempts_used'] for r in rows)))
    atomic_json(out/'scoreboard.json',scoreboard)
    print('Results exported to '+str(out))

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',default='config.json')
    sub=ap.add_subparsers(dest='command',required=True)
    doctor_p=sub.add_parser('doctor');doctor_p.add_argument('--model',default='qwen')
    run=sub.add_parser('run');run.add_argument('--model',help='One model label; omitted runs all enabled models')
    run.add_argument('--problem');run.add_argument('--repeat',type=int)
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
    if args.command=='submit-file':
        model=get_model(cfg,args.model);dj=dom_client(cfg,model)
        candidates=[p for p in cfg['problems'] if p['slug']==args.problem]
        if len(candidates)!=1:raise HarnessError('Unknown configured problem slug: '+args.problem)
        problem=candidates[0];validate_problem(dj,cfg,problem)
        source=Path(args.file).read_text(encoding='utf-8')
        result=dj.call('POST',contest_path(cfg['contest_id'],'submissions'),submission_payload(problem['judge_id'],cfg['language_id'],source))
        print('Submission ID:',result['id']);judgement,_=wait_for_judgement(dj,cfg,str(result['id']))
        print(json.dumps(judgement,indent=2));return
    models=[get_model(cfg,args.model)] if args.model else [m for m in cfg['models'] if m.get('enabled',True)]
    if not models:raise HarnessError('Enable at least one model in config.json.')
    problems=[p for p in cfg['problems'] if not args.problem or p['slug']==args.problem]
    if not problems:raise HarnessError('No matching configured problem.')
    repetitions=[args.repeat] if args.repeat is not None else list(range(1,cfg.get('repetitions',2)+1))
    if any(n<1 or n>cfg.get('repetitions',2) for n in repetitions):raise HarnessError('Repetition is outside configured range.')
    try:
        run_contest(cfg,models,problems,repetitions)
    finally:export(cfg)

if __name__=='__main__':
    try:main()
    except (HarnessError,ValueError,OSError) as exc:
        print('Stopped:',str(exc),file=sys.stderr);sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command to resume persisted runs.',file=sys.stderr);sys.exit(130)

