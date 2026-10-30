import json
from pathlib import Path
import tempfile
import unittest

from clearwake.local_ai import LocalWorker,MODEL
from relayloom.meta import SYNTHETIC_BRIEF
from relayloom.controller import Rejected


class LocalAITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ledger.sqlite3';self.calls=[]
        self.intent={'brief':SYNTHETIC_BRIEF,'refund_days':30,'audience':'Customers'}
    def send(self,path,payload=None):
        self.calls.append((path,payload))
        if path=='/api/tags':return {'models':[{'name':MODEL,'digest':'a'*64}]}
        body=json.loads(payload['messages'][1]['content'])
        return {'model':MODEL,'done':True,'done_reason':'stop','prompt_eval_count':100,'eval_count':40,
                'message':{'role':'assistant','content':json.dumps({'summary':'A synthetic tested summary.',**body['required_evidence']})}}
    def worker(self,send=None):return LocalWorker(model_digest='a'*64,ledger_path=self.path,send=send or self.send)
    def test_explicit_local_transport_and_usage(self):
        worker=self.worker();self.assertEqual(self.calls,[])
        result=worker.execute('request-1','room','product',self.intent,{})
        self.assertEqual(result['audience'],'Customers')
        self.assertEqual(worker.mode,'local-ai')
        self.assertEqual(worker.metrics('room')['reported_total_tokens'],140)
        self.assertEqual([p for p,_ in self.calls],['/api/tags','/api/chat'])
        request=self.calls[1][1]
        self.assertEqual(request['options']['num_thread'],2)
        self.assertNotIn('refund_days',json.loads(request['messages'][1]['content'])['inputs'])
    def test_replay_refused_after_reopen(self):
        self.worker().execute('same','room','engineering',self.intent,{})
        with self.assertRaises(Rejected):self.worker().execute('same','room','engineering',self.intent,{})
        self.assertEqual(len(self.calls),2)
    def test_model_digest_change_never_reaches_inference(self):
        def send(path,payload=None):self.calls.append(path);return {'models':[{'name':MODEL,'digest':'b'*64}]}
        worker=self.worker(send)
        with self.assertRaises(Rejected):worker.execute('one','room','product',self.intent,{})
        self.assertEqual(self.calls,['/api/tags'])
        self.assertEqual(worker.metrics('room')['unknown_usage_requests'],1)
    def test_invalid_intent_stops_before_reservation(self):
        worker=self.worker()
        with self.assertRaises(Rejected):worker.execute('one','room','product',{**self.intent,'brief':'Private upload'}, {})
        self.assertEqual(self.calls,[]);self.assertEqual(worker.metrics('room')['model_calls'],0)
    def test_bad_model_output_fails_independent_contract(self):
        def send(path,payload=None):
            response=self.send(path,payload)
            if path=='/api/chat':response['message']['content']=json.dumps({'summary':'Looks safe','refund_days':999,'boundary':'draft-only'})
            return response
        worker=self.worker(send)
        with self.assertRaises(Rejected):worker.execute('bad','room','engineering',self.intent,{})
        self.assertEqual(worker.metrics('room')['model_calls'],1)
