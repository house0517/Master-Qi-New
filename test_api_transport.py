import ast
import json
import unittest
from pathlib import Path
import httpx
from openai import OpenAI
from api_transport import build_chat_completion_kwargs, iter_chat_text, normalize_base_url, ResponseFormatError

class CompatibilityTests(unittest.TestCase):
    def test_kimi_parameters(self):
        for limit,temp in [(2400,.8),(8000,.8),(900,.1),(2500,.3)]:
            args=build_chat_completion_kwargs('kimi-k3',[],True,limit,temp)
            self.assertNotIn('temperature',args)
            self.assertNotIn('max_tokens',args)
            self.assertEqual(args['reasoning_effort'],'low')
            self.assertGreaterEqual(args['max_completion_tokens'],limit+4096)

    def test_other_provider(self):
        args=build_chat_completion_kwargs('other',[],False,2400,.8)
        self.assertEqual(args['temperature'],.8)
        self.assertEqual(args['max_tokens'],2400)
        self.assertNotIn('reasoning_effort',args)

    def client(self,ctype,body):
        def handler(request):
            self.assertEqual(request.url.path,'/v1/chat/completions')
            args=json.loads(request.content)
            self.assertEqual(args['reasoning_effort'],'low')
            self.assertNotIn('temperature',args)
            return httpx.Response(200,headers={'content-type':ctype},content=body)
        return OpenAI(api_key='test-only',base_url=normalize_base_url('https://api.moonshot.cn'),http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def args(self):
        return build_chat_completion_kwargs('kimi-k3',[{'role':'user','content':'test'}],True,2400,.8)

    def test_sse_and_length(self):
        for content,reason in [('正常正文','stop'),('','length')]:
            body='data: '+json.dumps({'choices':[{'index':0,'delta':{'content':content,'reasoning_content':'hidden'},'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n'
            with self.client('text/event-stream',body) as client:
                self.assertEqual(list(iter_chat_text(client,self.args())),[(content,reason)])

    def test_json(self):
        body=json.dumps({'choices':[{'message':{'content':'正常正文'},'finish_reason':'stop'}]})
        with self.client('application/json',body) as client:
            self.assertEqual(list(iter_chat_text(client,self.args())),[('正常正文','stop')])

    def test_html(self):
        with self.client('text/html','<html>home</html>') as client:
            with self.assertRaisesRegex(ResponseFormatError,'HTML'):
                list(iter_chat_text(client,self.args()))

    def test_call_sites(self):
        tree=ast.parse(Path(__file__).with_name('app.py').read_text())
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and ast.unparse(n.func)=='client.chat.completions.create']
        self.assertEqual(len(calls),2)
        for call in calls:
            self.assertEqual(len(call.keywords),1)
            self.assertIsNone(call.keywords[0].arg)
            self.assertEqual(ast.unparse(call.keywords[0].value.func),'build_chat_completion_kwargs')

if __name__=='__main__': unittest.main()
