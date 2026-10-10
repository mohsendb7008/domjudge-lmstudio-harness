"""Contest scheduling and provider integration against real local HTTP services."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import harness as h
from providers import generation_payload


class ContestTests(unittest.TestCase):
    def setUp(self):
        self.requests=[];self.generations=[];self.selections=[];self.submissions=[];self.loads=[];self.unloads=[]
        self.hold=False;self.selection_invalid=False;self.fail_generation=0;self.fail_load=False
        self.failure_status=429;self.failure_body={}
        test=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,value,status=200):
                raw=json.dumps(value).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                if self.path.endswith('/problems'):
                    self.reply([{'id':p,'time_limit':2} for p in ['p1','p2']])
                elif self.path.endswith('/languages/cpp'):self.reply({'id':'cpp'})
                elif self.path.endswith('/judgements'):
                    rows=[] if test.hold else [{'id':str(i),'submission_id':str(i),'end_time':'finished',
                                               'judgement_type_id':s['verdict']} for i,s in enumerate(test.submissions,1)]
                    self.reply(rows)
                elif self.path.endswith('/models'):self.reply({'data':[{'id':'alpha'},{'id':'beta'}]})
                else:self.reply({},404)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.requests.append((self.path,payload,dict(self.headers)))
                if self.path=='/api/v1/models/load':
                    if test.fail_load:self.reply({},503);return
                    test.loads.append(payload);self.reply({'instance_id':payload['model']+'-instance'});return
                if self.path=='/api/v1/models/unload':
                    test.unloads.append(payload);self.reply(payload);return
                if self.path.endswith('/chat/completions') or self.path.endswith('/messages'):
                    if test.fail_generation:
                        test.fail_generation-=1;self.reply(test.failure_body,test.failure_status);return
                    initial=payload['messages'][0]['content']
                    if initial.startswith('Choose the easiest'):
                        candidates=json.loads(initial.split('\n\n',1)[1])
                        test.selections.append(payload)
                        content='bad selection' if test.selection_invalid else json.dumps({'problem':candidates[-1]['slug']})
                    else:
                        test.generations.append(payload)
                        content='```cpp\nint main(){return 0;} // generation'+str(len(test.generations))+'\n```'
                    if self.path.endswith('/messages'):
                        self.reply({'content':[{'type':'text','text':content}],'stop_reason':'end_turn',
                                    'usage':{'input_tokens':7,'output_tokens':9}})
                    else:self.reply({'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                     'usage':{'prompt_tokens':7,'completion_tokens':9}})
                elif self.path.endswith('/submissions'):
                    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload['files'][0]['data']))) as z:
                        source=z.read('main.cpp').decode()
                    n=int(source.split('generation')[1].strip())
                    generation=test.generations[n-1];initial=generation['messages'][0]['content']
                    verdict='AC' if payload['problem']=='p1' and (generation['model'].startswith('beta') or 'HINT_p1' in initial) else 'WA'
                    test.submissions.append(dict(payload,verdict=verdict));self.reply({'id':str(len(test.submissions))},201)
                else:self.reply({},404)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.temp.name)
        for slug in ['p1','p2']:(self.root/(slug+'.txt')).write_text('Statement '+slug+'. Public sample only.')
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.cfg={'domjudge_api':self.base+'/api/v4','lmstudio_api':self.base+'/v1',
                  'lmstudio_management_api':self.base+'/api/v1','contest_id':'c1','language_id':'cpp',
                  'attempts':2,'repetitions':2,'problem_selection':'model','auto_load_models':False,
                  'generation_retries':1,'retry_backoff_s':0,'judge_timeout_s':0,'poll_interval_s':0,
                  'models':[{'label':name,'identifier':name,'username':name} for name in ['alpha','beta']],
                  'problems':[{'slug':slug,'judge_id':slug,'statement':slug+'.txt',
                               'difficulty':i+1,'hidden_hint':'HINT_'+slug} for i,slug in enumerate(['p1','p2'])]}
        self.env=patch.dict(os.environ,{'DOMJUDGE_PASSWORD':'secret-team','OPENAI_API_KEY':'secret-openai',
                                       'ANTHROPIC_API_KEY':'secret-claude'},clear=True);self.env.start()
    def tearDown(self):
        self.env.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def run_cli(self,*args):
        file=self.root/'config.json';file.write_text(json.dumps(self.cfg))
        with contextlib.redirect_stdout(io.StringIO()):h.main(['--config',str(file),'run',*args])
    def state(self,model,problem,repeat):
        path=self.root/'results'/model/problem/f'repeat-{repeat:02d}'/'state.json'
        return json.loads(path.read_text()) if path.exists() else None

    def test_inference_error_reports_structured_detail_and_redacts_credentials(self):
        self.fail_generation=1;self.failure_status=400
        self.failure_body={'error':{'message':'Context exceeded\nsecret-openai sk-proj-example-secret Bearer another-key',
                                    'code':'context_length_exceeded'},'request_dump':'PRIVATE_PROMPT'}
        client=h.model_client(self.cfg,dict(self.cfg['models'][0],provider='openai',api_base=self.base+'/v1'))
        with self.assertRaises(h.ApiError) as raised:client.call('POST','chat/completions',{})
        error=raised.exception
        self.assertEqual(error.status,400);self.assertEqual(error.error_code,'context_length_exceeded')
        self.assertIn('Context exceeded',str(error));self.assertIn('[REDACTED]',str(error))
        for secret in ('secret-openai','sk-proj-example-secret','another-key','PRIVATE_PROMPT','\n'):
            self.assertNotIn(secret,str(error))

    def test_anthropic_header_key_is_redacted(self):
        self.fail_generation=1;self.failure_body={'error':{'message':'Invalid secret-claude'}}
        model=dict(self.cfg['models'][0],provider='anthropic',api_base=self.base+'/v1')
        with self.assertRaises(h.ApiError) as raised:h.model_client(self.cfg,model).call('POST','messages',{})
        self.assertNotIn('secret-claude',str(raised.exception));self.assertIn('[REDACTED]',str(raised.exception))

    def test_judge_error_keeps_server_body_private(self):
        self.fail_generation=1;self.failure_body={'error':{'message':'PRIVATE_JUDGE_DETAIL'}}
        with self.assertRaises(h.ApiError) as raised:h.Client(self.base+'/v1').call('POST','chat/completions',{})
        self.assertNotIn('PRIVATE_JUDGE_DETAIL',str(raised.exception))

    def test_error_detail_handles_unstructured_and_oversized_messages(self):
        client=h.Client(self.base,inference=True)
        for raw in (b'<html>private</html>',b'[]',b'{"error": null}',b'{"error": {"message": []}}'):
            self.assertEqual(client.error_detail(raw),('',None))
        detail,code=client.error_detail(json.dumps({'error':'x'*5000}).encode())
        self.assertEqual(len(detail),800);self.assertIsNone(code)

    def test_quota_error_stops_without_retry_and_selection_identifies_stage(self):
        self.fail_generation=5;self.failure_status=429
        self.failure_body={'error':{'message':'Add API credits','code':'insufficient_quota'}}
        with self.assertRaises(h.ApiError) as raised:self.run_cli('--model','alpha')
        self.assertEqual(self.fail_generation,4);self.assertEqual(len(self.requests),1)
        self.assertIn('Problem selection failed:',str(raised.exception));self.assertIn('Add API credits',str(raised.exception))
        self.assertEqual(self.submissions,[])

    def test_probe_does_not_require_judge_ids_password_or_write_contest_state(self):
        self.cfg['contest_id']=None;self.cfg['language_id']=None
        file=self.root/'config.json';file.write_text(json.dumps(self.cfg))
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()) as output:
            h.main(['--config',str(file),'probe-model','--model','alpha'])
        self.assertIn('Inference request succeeded',output.getvalue())
        self.assertEqual(len(self.generations),1);self.assertEqual(self.generations[0]['max_tokens'],256)
        self.assertEqual(self.generations[0]['messages'],[{'role':'user','content':'Reply with OK.'}])
        self.assertEqual(self.submissions,[]);self.assertEqual(self.selections,[])
        self.assertFalse((self.root/'results').exists())

    def test_probe_error_is_immediate(self):
        self.fail_generation=5;self.failure_status=400;self.failure_body={'error':'Channel Error'}
        with self.assertRaisesRegex(h.ApiError,'HTTP 400. Channel Error'):
            with contextlib.redirect_stdout(io.StringIO()):h.probe_model(dict(self.cfg,_root=str(self.root)),'alpha')
        self.assertEqual(self.fail_generation,4);self.assertEqual(self.submissions,[])

    def test_environment_field_rejects_literal_key_without_echoing_it(self):
        self.cfg['models'][0]['api_key_env']='sk-proj-example-secret'
        file=self.root/'config.json';file.write_text(json.dumps(self.cfg))
        with self.assertRaises(h.HarnessError) as raised:h.load_config(file)
        self.assertIn('environment variable',str(raised.exception))
        self.assertNotIn('sk-proj-example-secret',str(raised.exception))

    def test_model_selects_and_finishes_attempts_round_two_hints_only(self):
        self.run_cli()
        jobs=json.loads((self.root/'results/contest.json').read_text())['jobs']
        self.assertEqual([(j['repeat'],j['model'],j['problem']) for j in jobs],
                         [(1,'alpha','p2'),(1,'alpha','p1'),(1,'beta','p2'),(1,'beta','p1'),
                          (2,'alpha','p2'),(2,'alpha','p1'),(2,'beta','p2')])
        self.assertEqual(self.state('alpha','p1',1)['status'],'EXHAUSTED')
        self.assertEqual(self.state('alpha','p1',2)['status'],'ACCEPTED')
        self.assertIsNone(self.state('beta','p1',2))
        for model in ['alpha','beta']:
            for slug in ['p1','p2']:
                state=self.state(model,slug,1)
                self.assertFalse(state['hint_used']);self.assertNotIn('HINT_',json.dumps(state))
        self.assertTrue(self.state('alpha','p1',2)['hint_used'])
        self.assertEqual([len(self.state('alpha',p,r)['attempts']) for r,p in [(1,'p2'),(1,'p1'),(2,'p2'),(2,'p1')]], [2,2,2,1])
        self.assertTrue(all('HINT_' not in json.dumps(s) and 'hidden_hint' not in json.dumps(s) for s in self.selections))
        n=len(self.generations);s=len(self.selections);self.run_cli()
        self.assertEqual((len(self.generations),len(self.selections)),(n,s))
        board=json.loads((self.root/'results/scoreboard.json').read_text())
        self.assertEqual([r['solved'] for r in board],[1,1]);self.assertTrue(all(r['contest_complete'] for r in board))
        self.assertEqual(board[0]['solved_without_hint'],[]);self.assertEqual(board[1]['solved_without_hint'],['p1'])

    def test_easiest_policy_requires_no_selector_calls(self):
        self.cfg['problem_selection']='easiest';self.run_cli('--model','alpha','--repeat','1')
        self.assertEqual(self.selections,[])
        self.assertEqual([s['problem'] for s in self.submissions],['p1','p1','p2','p2'])

    def test_invalid_selector_falls_back_and_does_not_loop(self):
        self.selection_invalid=True;self.run_cli('--model','alpha','--repeat','1')
        self.assertEqual([s['problem'] for s in self.submissions],['p1','p1','p2','p2'])

    def test_pending_resume_does_not_reselect_or_repost(self):
        self.hold=True
        with self.assertRaisesRegex(h.HarnessError,'stays pending'):self.run_cli('--model','alpha')
        self.assertEqual((len(self.selections),len(self.generations),len(self.submissions)),(1,1,1))
        self.hold=False;self.run_cli('--model','alpha')
        self.assertEqual(len(self.selections),4)
        self.assertEqual(len(self.submissions),7)

    def test_selected_job_survives_crash_before_job_state(self):
        with patch.object(h,'run_job',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):self.run_cli('--model','alpha','--repeat','1')
        self.assertIsNone(self.state('alpha','p2',1));self.assertEqual(len(self.selections),1)
        self.run_cli('--model','alpha','--repeat','1');self.assertEqual(len(self.selections),2)

    def test_all_attempts_exhausted_and_completed_rerun_has_no_generations(self):
        self.cfg['models']=self.cfg['models'][:1];self.cfg['problems']=self.cfg['problems'][1:]
        self.cfg.pop('attempts');self.run_cli()
        self.assertEqual(len(self.submissions),20)
        self.assertEqual(len(self.state('alpha','p2',1)['attempts']),10)
        self.assertTrue(all(len(g['messages'])<=3 for g in self.generations))
        self.assertGreater(len(self.state('alpha','p2',1)['messages']),3)
        self.assertIn('generation9',self.generations[9]['messages'][1]['content'])
        self.run_cli();self.assertEqual(len(self.submissions),20)

    def test_configuration_and_prompt_changes_rejected_even_for_solved(self):
        self.run_cli('--model','beta','--problem','p1')
        (self.root/'p1.txt').write_text('Changed statement')
        with self.assertRaisesRegex(h.HarnessError,'Configuration changed'):self.run_cli('--model','beta')

    def test_round_two_requires_completed_round_one(self):
        with self.assertRaisesRegex(h.HarnessError,'Finish round 1'):self.run_cli('--model','alpha','--repeat','2')

    def test_disabled_models_are_omitted_and_explicit_model_is_allowed(self):
        self.cfg['models'][1]['enabled']=False;self.run_cli('--repeat','1')
        self.assertTrue(all(g['model']=='alpha' for g in self.generations))
        self.run_cli('--model','beta','--repeat','1')
        self.assertEqual(self.state('beta','p1',1)['status'],'ACCEPTED')

    def test_lmstudio_load_unload_each_active_model_round(self):
        self.cfg['auto_load_models']=True;self.run_cli()
        self.assertEqual([p['model'] for p in self.loads],['alpha','beta','alpha','beta'])
        self.assertEqual([p['instance_id'] for p in self.unloads],['alpha-instance','beta-instance','alpha-instance','beta-instance'])
        self.assertTrue(all(g['model'].endswith('-instance') for g in self.generations))

    def test_load_failure_does_not_generate_or_submit(self):
        self.cfg['auto_load_models']=True;self.fail_load=True
        with self.assertRaises(h.ApiError):self.run_cli('--model','alpha')
        self.assertEqual((len(self.generations),len(self.submissions)),(0,0))

    def test_lmstudio_unloads_when_judging_times_out(self):
        self.cfg['auto_load_models']=True;self.hold=True
        with self.assertRaisesRegex(h.HarnessError,'stays pending'):self.run_cli('--model','alpha')
        self.assertEqual(self.unloads,[{'instance_id':'alpha-instance'}])

    def test_missing_cloud_key_stops_before_local_generation(self):
        self.cfg['models'][1].update(provider='openai',api_key_env='UNSET_TEST_API_KEY')
        with self.assertRaisesRegex(h.HarnessError,'UNSET_TEST_API_KEY'):self.run_cli()
        self.assertEqual((len(self.generations),len(self.submissions)),(0,0))

    def test_claude_verdict_feedback_and_round_two_hint(self):
        self.cfg['models']=[dict(label='claude',identifier='alpha',username='claude',provider='anthropic',api_base=self.base+'/v1')]
        self.run_cli('--problem','p1')
        self.assertEqual(self.state('claude','p1',1)['status'],'EXHAUSTED')
        self.assertEqual(self.state('claude','p1',2)['status'],'ACCEPTED')
        self.assertEqual([m['role'] for m in self.generations[1]['messages']],['user','assistant','user'])
        self.assertIn('DOMjudge verdict: WA',self.generations[1]['messages'][-1]['content'])

    def test_hint_changes_rejected_before_resuming(self):
        self.run_cli('--model','alpha','--repeat','1')
        self.cfg['problems'][0]['hidden_hint']='new hint'
        with self.assertRaisesRegex(h.HarnessError,'Configuration changed'):self.run_cli('--model','alpha')

    def test_cloud_provider_wire_format_auth_and_secret_free_artifacts(self):
        for provider,secret,header in [('openai','secret-openai','Authorization'),('anthropic','secret-claude','X-Api-Key')]:
            with self.subTest(provider=provider):
                self.cfg['output_directory']='results-'+provider
                self.cfg['models']=[dict(label=provider,identifier='beta',username=provider,provider=provider,api_base=self.base+'/v1')]
                self.run_cli('--problem','p1')
                requests=[r for r in self.requests if r[0].endswith('/messages' if provider=='anthropic' else '/chat/completions')]
                path,payload,headers=requests[-1]
                self.assertEqual(headers[header],secret if provider=='anthropic' else 'Bearer '+secret)
                self.assertNotIn('seed',payload);self.assertNotIn('temperature',payload);self.assertNotIn('top_p',payload)
                self.assertIn('max_tokens' if provider=='anthropic' else 'max_completion_tokens',payload)
                for file in (self.root/('results-'+provider)).rglob('*.json'):
                    self.assertNotIn(secret,file.read_text())
                if provider=='anthropic':
                    self.assertEqual(headers['Anthropic-Version'],'2023-06-01')
                    state=json.loads((self.root/'results-anthropic/anthropic/p1/repeat-01/state.json').read_text())
                    self.assertEqual(state['attempts'][0]['usage']['prompt_tokens'],7)

    def test_transient_inference_retries_without_extra_attempt(self):
        self.fail_generation=1;self.cfg['problem_selection']='configured'
        self.run_cli('--model','beta','--problem','p1')
        self.assertEqual((len(self.generations),len(self.submissions)),(1,1))
        self.assertEqual(len(self.state('beta','p1',1)['attempts']),1)


class ConfigTests(unittest.TestCase):
    def test_validations_and_round_one_hint_isolation(self):
        cfg={'domjudge_api':'http://localhost','models':[{'label':'m'}],
             'problems':[{'slug':'p','hidden_hint':'private'}],'hidden_hints':{'p':'fallback'}}
        self.assertEqual(h.hidden_hint(cfg,cfg['problems'][0],1),'')
        self.assertEqual(h.hidden_hint(cfg,cfg['problems'][0],2),'private')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            path=Path(d)/'config.json'
            for field,value in [('attempts',11),('repetitions',3),('attempts',True),('problem_selection','random')]:
                with self.subTest(field=field,value=value):
                    path.write_text(json.dumps(dict(cfg,**{field:value})))
                    with self.assertRaises(h.HarnessError):h.load_config(path)
            path.write_text(json.dumps(cfg));self.assertEqual(h.load_config(path)['models'][0]['label'],'m')

    def test_cloud_sampling_is_explicit_per_model(self):
        for provider in ['openai','anthropic']:
            payload=generation_payload({'temperature':0.2,'top_p':0.9},{'provider':provider,'identifier':'model'},[],1)
            self.assertNotIn('temperature',payload);self.assertNotIn('top_p',payload)
        payload=generation_payload({},dict(provider='openai',identifier='model',reasoning_effort='high'),[],1)
        self.assertEqual(payload['reasoning_effort'],'high')

    def test_claude_selection_leaves_room_for_explicit_thinking(self):
        payload=generation_payload({'selection_max_tokens':1024},
            dict(provider='anthropic',identifier='model',thinking={'type':'enabled','budget_tokens':4096}),[],1,selection=True)
        self.assertGreater(payload['max_tokens'],payload['thinking']['budget_tokens'])


if __name__=='__main__':unittest.main()
