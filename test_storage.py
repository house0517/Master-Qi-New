import ast
import datetime
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import urllib.request
import urllib.error

class State(dict):
    def __getattr__(self,key): return self.get(key)
    def __setattr__(self,key,value): self[key]=value

class FakeSt:
    def __init__(self): self.session_state=State(); self.messages=[]
    def cache_data(self,*a,**kw):
        def decorate(fn): fn.clear=lambda: None; return fn
        return decorate
    def __getattr__(self,name): return lambda *args,**kw:self.messages.append((name,args))

FUNCTIONS={'normalize_record_identity','validate_record_identity','get_supabase_config','has_supabase_secrets','looks_like_jwt','supabase_request','get_supabase_table','normalize_supabase_row','read_supabase_records','active_storage_backend','configured_storage_backend','history_to_text','history_from_text','init_db','load_records_from_sqlite','save_to_sqlite','merge_local_only_records','load_records','load_record_by_id','restore_record_to_session','save_to_supabase','save_record','sync_local_records_to_supabase'}
def context():
    source=Path(__file__).with_name('app.py').read_text()
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in FUNCTIONS]
    ns={'st':FakeSt(),'json':json,'ast':ast,'datetime':datetime,'sqlite3':sqlite3,'urllib':urllib,'re':re,'RECORD_COLUMNS':['id','name','birth_info','report','history','date','ptype'],'SUPABASE_TIMEOUT_SECONDS':20,'STORAGE_SHORT_LABELS':{'supabase':'Supabase','gsheets':'Google Sheets','sqlite':'本地 SQLite'}}
    ns['get_config']=lambda section,key,env,default='': {'storage':{'backend':'supabase'},'supabase':{'url':'https://example.invalid','service_role_key':'test-only'}}.get(section,{}).get(key,default)
    ns['has_gsheets_secrets']=lambda:False
    ns['save_to_gsheets']=lambda *a:False
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<storage>','exec'),ns)
    return ns

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.ns=context(); self.temp=tempfile.TemporaryDirectory()
        self.ns['LOCAL_DB_PATH']=str(Path(self.temp.name)/'records.db')
        self.ns['init_db']()
    def tearDown(self): self.temp.cleanup()
    def test_cloud_roundtrip_and_restore(self):
        rows=[]
        def request(method,path,payload=None,prefer=''):
            self.assertTrue(path.startswith('master_qi_records?'))
            if method=='POST': rows[:]=[dict(payload,id=1)]
            return list(rows) if method=='GET' else None
        self.ns['supabase_request']=request
        self.assertTrue(self.ns['save_record']('测试','2000-01-01','正文',[{'question':'问','answer':'答'}],'single'))
        record=self.ns['load_record_by_id'](1)
        self.assertTrue(self.ns['restore_record_to_session'](record))
        state=self.ns['st'].session_state
        self.assertEqual(state.main_report,'正文');self.assertEqual(state.chat_history[0]['answer'],'答')
    def test_cloud_failure_preserves_sqlite(self):
        self.ns['supabase_request']=Mock(side_effect=RuntimeError('offline'))
        self.assertTrue(self.ns['save_record']('测试','2000-01-01','不能丢失',[]))
        self.assertIn('临时',self.ns['st'].session_state.last_save_error)
        self.assertEqual(self.ns['load_records']()[0]['report'],'不能丢失')
    def test_missing_config_does_not_claim_cloud_success(self):
        self.ns['get_config']=lambda s,k,e,default='':default
        self.assertTrue(self.ns['save_record']('测试','2000-01-01','正文',[]))
        self.assertIn('尚未同步云端',self.ns['st'].session_state.last_save_error)
    def test_types_are_not_overwritten(self):
        for ptype in ('single','double','bazi'):
            self.ns['save_to_sqlite']('同名','同生日',ptype,[],ptype)
        self.ns['save_to_sqlite']('同名','同生日','更新',[],'single')
        rows=self.ns['load_records_from_sqlite']()
        self.assertEqual(len(rows),3)
        self.assertEqual({r['ptype']:r['report'] for r in rows},{'single':'更新','double':'double','bazi':'bazi'})
    def test_pagination(self):
        def request(method,path):
            offset=int(path.split('offset=')[1])
            return [{'id':i+1,'report':'正文'} for i in range(offset,min(offset+500,1002))]
        self.ns['supabase_request']=request
        self.assertEqual(len(self.ns['read_supabase_records']()),1002)
    def test_local_upload_preserves_cloud_records(self):
        self.ns['save_to_sqlite']('已有','生日','旧版本',[])
        self.ns['save_to_sqlite']('未同步','生日','保留报告',[{'question':'问','answer':'答'}])
        posts=[]
        def request(method,path,payload=None,prefer=''):
            if method=='GET':return [{'id':1,'name':'已有','birth_info':'生日','ptype':'single','report':'新版本'}]
            self.assertIn('ignore-duplicates',prefer);posts.append(payload)
        self.ns['supabase_request']=request
        self.assertEqual(self.ns['sync_local_records_to_supabase'](),(1,1,0))
        self.assertEqual(posts[0]['name'],'未同步');self.assertEqual(json.loads(posts[0]['history'])[0]['answer'],'答')
    def test_empty_report_is_rejected(self):
        request=Mock();self.ns['supabase_request']=request
        self.assertFalse(self.ns['save_record']('测试','生日',' ',[]));request.assert_not_called()
    def test_table_identifier_and_backend(self):
        self.assertEqual(self.ns['get_supabase_table'](),'master_qi_records')
        self.ns['get_config']=lambda s,k,e,default='':'records?select=*' if k=='table' else default
        with self.assertRaises(ValueError):self.ns['get_supabase_table']()
    def test_local_read_after_new_process(self):
        self.ns['save_to_sqlite']('测试','生日','持久正文',[{'question':'追问','answer':'回答'}],'bazi')
        second=context();second['LOCAL_DB_PATH']=self.ns['LOCAL_DB_PATH']
        second['supabase_request']=lambda *a:[]
        rows=second['load_records']()
        self.assertEqual(rows[0]['report'],'持久正文');self.assertEqual(rows[0]['ptype'],'bazi')

if __name__=='__main__':unittest.main()
