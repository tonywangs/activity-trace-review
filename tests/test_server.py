import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import unittest
from unittest.mock import patch
from activity_trace_review import core, server
from activity_trace_review.demo import demo_files, example_review

class ServerTransactions(unittest.TestCase):
    def post(self, instance, body, token=None):
        def request():
            connection=http.client.HTTPConnection('127.0.0.1',instance.server_port,timeout=5)
            try:
                connection.request('POST','/api/import',body=body,
                                   headers={'Content-Type':'application/json','X-Review-Token':instance.token if token is None else token})
                response=connection.getresponse()
                return response.status,json.loads(response.read())
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(request)
            instance.handle_request()
            return future.result(timeout=5)

    def test_response_serialization_failure_preserves_source_and_review(self):
        source=core.load_files(demo_files())
        with server.Workbench(source=source) as instance:
            review=example_review(source);instance.review=review
            files=demo_files();trace=json.loads(files['trace.json']);trace['actions'][0]['text']['value']='new source'
            files['trace.json']=core.dumps(trace)
            body=json.dumps({'files':{name:base64.b64encode(data).decode() for name,data in files.items()}})
            def serialize(value):
                if type(value) is dict and 'trace' in value:
                    raise core.Invalid('Injected response serialization failure')
                return core.dumps(value)
            with patch.object(server,'dumps',serialize):
                status,data=self.post(instance,body)
            self.assertEqual(status,400);self.assertIn('serialization',data['error'])
            self.assertIs(instance.source,source);self.assertIs(instance.review,review)

    def test_non_ascii_auth_rejected_without_state_change(self):
        with server.Workbench() as instance:
            status,_=self.post(instance,'{}',token='é')
            self.assertEqual(status,400);self.assertIsNone(instance.source)

if __name__=='__main__':unittest.main()
