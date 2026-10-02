"""Exercise the runner through real HTTP requests to fake local services."""
import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import harness as h


class Backend:
    def __init__(self):
        self.generations=[];self.submissions=[];self.hold=False;self.reject=None
        self.ambiguous=False;self.format_error=False


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.backend=Backend();backend=self.backend
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send_json(self,value,status=200):
                raw=json.dumps(value).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/v1/chat/completions':
                    backend.generations.append(payload)
                    content='```cpp\nint main(){return '+str(len(backend.generations))+';}\n```'
                    if backend.format_error:content='I cannot provide a program.'
                    self.send_json({'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':50,'completion_tokens':20}})
                elif self.path=='/api/v4/contests/c1/submissions':
                    if backend.reject:
                        self.send_json({'error':'rejected'},backend.reject);return
                    backend.submissions.append(payload)
                    if backend.ambiguous:
                        self.send_json({'error':'lost response'},500);return
                    self.send_json({'id':str(len(backend.submissions))},201)
                else:self.send_json({},404)
            def do_GET(self):
                if self.path=='/api/v4/contests/c1/judgements':
                    rows=[] if backend.hold else [
                        {'id':str(i),'submission_id':str(i),'judgement_type_id':'WA' if i==1 else 'AC',
                         'end_time':'2026-10-02T12:00:00Z','max_run_time':0.12}
                        for i in range(1,len(backend.submissions)+1)]
                    self.send_json(rows)
                elif self.path=='/api/v4/contests/c1/problems':
                    self.send_json([{'id':'p1','name':'Example','time_limit':2}])
                elif self.path=='/api/v4/languages/cpp':self.send_json({'id':'cpp'})
                elif self.path=='/v1/models':self.send_json({'data':[{'id':'fake-model'}]})
                else:self.send_json({},404)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());root=Path(self.temp.name)
        (root/'prompt.txt').write_text('Output an integer. Public sample: 1.',encoding='utf-8')
        base=f'http://127.0.0.1:{self.server.server_port}'
        self.model={'label':'qwen','identifier':'fake-model','username':'team'}
        self.problem={'slug':'example','judge_id':'p1','statement':'prompt.txt'}
        self.cfg={'_root':str(root),'domjudge_api':base+'/api/v4','lmstudio_api':base+'/v1',
                  'contest_id':'c1','language_id':'cpp','attempts':3,'repetitions':1,
                  'judge_timeout_s':0,'poll_interval_s':0,'models':[self.model],'problems':[self.problem]}
        self.dj=h.Client(self.cfg['domjudge_api'],'team','test-password');self.lm=h.Client(self.cfg['lmstudio_api'])
        self.metadata=h.validate_problem(self.dj,self.cfg,self.problem)
        self.state_path=root/'results/qwen/example/repeat-01/state.json'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def run_job(self):
        with contextlib.redirect_stdout(io.StringIO()):
            h.run_job(self.cfg,self.model,self.problem,1,self.dj,self.lm,self.metadata)
    def state(self):return json.loads(self.state_path.read_text())

    def test_wa_then_ac_with_feedback_and_resume(self):
        self.run_job();state=self.state()
        self.assertEqual(state['status'],'ACCEPTED')
        self.assertEqual([a['verdict'] for a in state['attempts']],['WA','AC'])
        self.assertIn('DOMjudge verdict: WA',self.backend.generations[1]['messages'][-1]['content'])
        self.assertEqual([m['role'] for m in self.backend.generations[1]['messages']],['user','assistant','user'])
        for payload in self.backend.submissions:
            self.assertEqual((payload['problem'],payload['language']),('p1','cpp'))
            self.assertEqual(payload['files'][0]['mime'],'application/zip')
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload['files'][0]['data']))) as z:
                self.assertEqual(z.namelist(),['main.cpp']);self.assertIn(b'main()',z.read('main.cpp'))
        self.run_job()
        self.assertEqual(len(self.backend.submissions),2)
        with contextlib.redirect_stdout(io.StringIO()):h.export(self.cfg)
        summary=json.loads((Path(self.cfg['_root'])/'results/summary.json').read_text())[0]
        self.assertEqual((summary['accepted'],summary['first_accepted'],summary['completed_runs']),(1,0,1))
        self.assertIsNone(state['attempts'][0]['memory_mb'])

    def test_pending_timeout_resumes_same_submission(self):
        self.backend.hold=True
        with self.assertRaisesRegex(h.HarnessError,'stays pending'):self.run_job()
        self.assertEqual(self.state()['attempts'][0]['submission_id'],'1')
        self.assertEqual(self.state()['attempts'][0]['status'],'PENDING')
        with contextlib.redirect_stdout(io.StringIO()):h.export(self.cfg)
        summary=json.loads((Path(self.cfg['_root'])/'results/summary.json').read_text())[0]
        self.assertEqual(summary['completed_runs'],0);self.assertIsNone(summary['acceptance_rate'])
        self.backend.hold=False;self.run_job()
        self.assertEqual(len(self.backend.submissions),2)
        self.assertEqual(len(self.backend.generations),2)

    def test_unknown_submission_outcome_never_reposts(self):
        self.backend.ambiguous=True
        with self.assertRaises(h.ApiError):self.run_job()
        self.assertEqual(self.state()['attempts'][0]['status'],'SUBMITTING')
        with self.assertRaisesRegex(h.HarnessError,'outcome is unknown'):self.run_job()
        self.assertEqual(len(self.backend.submissions),1)
        self.assertEqual(len(self.backend.generations),1)

    def test_definite_rejection_reuses_generated_source(self):
        self.backend.reject=403
        with self.assertRaises(h.ApiError):self.run_job()
        self.assertEqual(self.state()['attempts'][0]['status'],'GENERATED')
        self.backend.reject=None;self.run_job()
        self.assertEqual(len(self.backend.generations),2)
        self.assertEqual(len(self.backend.submissions),2)

    def test_invalid_generation_is_counted_without_submission(self):
        self.backend.format_error=True;self.run_job()
        state=self.state();self.assertEqual(state['status'],'EXHAUSTED')
        self.assertEqual(len(self.backend.submissions),0)
        self.assertEqual([a['verdict'] for a in state['attempts']],['GENERATION_FORMAT_ERROR']*3)
        self.assertEqual([m['role'] for m in self.backend.generations[1]['messages']],['user','assistant','user'])

    def test_configuration_change_cannot_mix_existing_results(self):
        self.run_job();self.cfg['temperature']=0.8
        with self.assertRaisesRegex(h.HarnessError,'Configuration changed'):self.run_job()


class ProtocolTests(unittest.TestCase):
    def test_final_judgement_waits_for_latest_valid_completion(self):
        rows=[{'id':'2','submission_id':'7','end_time':'finished','judgement_type_id':'AC'},
              {'id':'3','submission_id':'7','end_time':None,'judgement_type_id':'AC'},
              {'id':'4','submission_id':'7','valid':False,'end_time':'finished','judgement_type_id':'WA'}]
        self.assertIsNone(h.final_judgement(rows,'7'))
        rows[1]['end_time']='finished';self.assertEqual(h.final_judgement(rows,'7')['id'],'3')
        self.assertIsNone(h.final_judgement(rows,'8'))
    def test_code_extraction_removes_thinking_and_rejects_ambiguity(self):
        self.assertEqual(h.extract_cpp('<think>reasoning</think>\n```cpp\nint main(){}\n```'),'int main(){}\n')
        with self.assertRaises(h.HarnessError):h.extract_cpp('```cpp\nint main(){}\n```\n```cpp\nint main(){}\n```')
        with self.assertRaises(h.HarnessError):h.extract_cpp('No solution.')


if __name__=='__main__':unittest.main()
