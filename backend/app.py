"""Intranet review application. Run with: uvicorn backend.app:app"""
import hashlib
import hmac
import io
import ipaddress
import os
import secrets
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from docx import Document as WordDocument
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session as DbSession

from .ai import evaluate
from .catalog import import_workbook, select_requirements, selection_summary
from .checks import compare_assets, issue, match_requirement, risk_review
from .db import (DATA, Base, engine, Session, User, LoginSession, Project, Member, Document,
                 Knowledge, ModelConfig, Run, Task, Issue, Audit, public)
from .documents import CHAPTERS, parse_docx

app = FastAPI(title='等保测评报告评审平台', docs_url=None, redoc_url=None)
POOL = ThreadPoolExecutor(max_workers=4)
COOKIE = 'review_session'
ROLES = {'survey', 'plan', 'report'}
MODULES = {'assets_full', 'assets_sample', 'appendix_d', 'high_risk'}


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 250_000)
    return salt.hex() + ':' + value.hex()


def password_valid(password, saved):
    salt, _ = saved.split(':', 1)
    return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), saved)


def audit(db, user, action, project=None, **detail):
    db.add(Audit(user_id=user.id if user else None, project_id=project, action=action, detail=detail))


def master_key():
    path = DATA / 'model.key'
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try: os.chmod(path, 0o600)
        except OSError: pass
    return path.read_bytes()


@app.on_event('startup')
def startup():
    Base.metadata.create_all(engine)
    with Session() as db:
        if not db.scalar(select(User.id).limit(1)):
            secret = secrets.token_urlsafe(20)
            db.add(User(username='admin', display_name='管理员', password_hash=password_hash(secret), admin=True))
            db.commit()
            path = DATA / 'bootstrap-admin.txt'
            path.write_text('用户名：admin\n初始密码：' + secret + '\n首次登录后请修改。\n', encoding='utf-8')
            try: os.chmod(path, 0o600)
            except OSError: pass
    master_key()
    POOL.submit(recover_tasks)


def db_session():
    with Session() as db:
        yield db


def current(request: Request, db: DbSession = Depends(db_session)):
    token = request.cookies.get(COOKIE, '')
    if not token: raise HTTPException(401, '请先登录')
    sess = db.scalar(select(LoginSession).where(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not sess or sess.expires_at < time.time(): raise HTTPException(401, '登录已过期')
    user = db.get(User, sess.user_id)
    if not user or not user.active: raise HTTPException(401, '用户不可用')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('x-csrf-token') != sess.csrf: raise HTTPException(403, '请求校验失败')
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            raise HTTPException(403, '请求来源不匹配')
    return user, sess


def admin(auth=Depends(current)):
    if not auth[0].admin: raise HTTPException(403, '需要管理员权限')
    return auth[0]


def project_access(db, project_id, user):
    project = db.get(Project, project_id)
    if not project or (not user.admin and not db.scalar(select(Member.id).where(Member.project_id == project_id, Member.user_id == user.id))):
        raise HTTPException(404, '项目不存在或无权限')
    return project


def payload(request_data, keys):
    if not isinstance(request_data, dict) or any(k not in request_data for k in keys):
        raise HTTPException(422, '缺少必要字段')
    return request_data


@app.post('/api/login')
def login(body: dict, response: Response, request: Request, db=Depends(db_session)):
    origin = request.headers.get('origin')
    if origin and urlparse(origin).netloc != request.headers.get('host'): raise HTTPException(403, '请求来源不匹配')
    name = str(body.get('username', ''))[:100]
    user = db.scalar(select(User).where(User.username == name))
    if not user or not user.active or user.locked_until > time.time() or not password_valid(str(body.get('password', '')), user.password_hash):
        if user and user.active:
            user.failures += 1
            if user.failures >= 5: user.locked_until = time.time() + 900; user.failures = 0
            db.commit()
        raise HTTPException(401, '用户名或密码错误，连续失败会暂时锁定账号')
    user.failures = 0; user.locked_until = 0
    token = secrets.token_urlsafe(40); csrf = secrets.token_urlsafe(32)
    db.add(LoginSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), csrf=csrf, expires_at=time.time()+8*3600))
    audit(db, user, 'login'); db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=8*3600)
    return {'user':public(user, ('password_hash','failures','locked_until')), 'csrf':csrf}


@app.get('/api/me')
def me(auth=Depends(current)):
    user, session = auth
    return {'user':public(user, ('password_hash','failures','locked_until')), 'csrf':session.csrf}


@app.post('/api/logout')
def logout(response: Response, auth=Depends(current), db=Depends(db_session)):
    db.delete(auth[1]); audit(db, auth[0], 'logout'); db.commit(); response.delete_cookie(COOKIE)
    return {'ok':True}


@app.post('/api/me/password')
def change_password(body: dict, auth=Depends(current), db=Depends(db_session)):
    user = db.get(User, auth[0].id)
    if not password_valid(str(body.get('old', '')), user.password_hash): raise HTTPException(422, '原密码错误')
    new = str(body.get('new', ''))
    if len(new) < 12: raise HTTPException(422, '新密码至少12位')
    user.password_hash = password_hash(new); audit(db,user,'password_changed'); db.commit()
    if user.username=='admin':(DATA / 'bootstrap-admin.txt').unlink(missing_ok=True)
    return {'ok':True}


@app.get('/api/users')
def users(_=Depends(admin), db=Depends(db_session)):
    return [public(x, ('password_hash','failures','locked_until')) for x in db.scalars(select(User).order_by(User.created_at))]


@app.post('/api/users')
def add_user(body: dict, user=Depends(admin), db=Depends(db_session)):
    payload(body, ('username','display_name','password'))
    if len(body['password']) < 12: raise HTTPException(422, '密码至少12位')
    if db.scalar(select(User.id).where(User.username==body['username'])): raise HTTPException(409,'用户名已存在')
    row=User(username=body['username'][:100], display_name=body['display_name'][:150],password_hash=password_hash(body['password']),admin=bool(body.get('admin',False)))
    db.add(row);audit(db,user,'user_created',user_id=row.username);db.commit()
    return public(row,('password_hash','failures','locked_until'))


@app.get('/api/projects')
def projects(auth=Depends(current), db=Depends(db_session)):
    user=auth[0]
    rows=db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [public(p) for p in rows if user.admin or db.scalar(select(Member.id).where(Member.project_id==p.id,Member.user_id==user.id))]


@app.post('/api/projects')
def add_project(body: dict, auth=Depends(current), db=Depends(db_session)):
    name=str(body.get('name','')).strip()
    if not name or len(name)>200:raise HTTPException(422,'项目名称不能为空且不超过200字')
    p=Project(name=name, owner_id=auth[0].id,config={'s':3,'a':3,'g':3,'extensions':[],'aliases':{},'matches':{}})
    db.add(p);db.flush();db.add(Member(project_id=p.id,user_id=auth[0].id,role='owner'))
    audit(db,auth[0],'project_created',p.id);db.commit();return public(p)


@app.get('/api/projects/{pid}')
def get_project(pid:str,auth=Depends(current),db=Depends(db_session)):
    return public(project_access(db,pid,auth[0]))


@app.patch('/api/projects/{pid}')
def edit_project(pid:str,body:dict,auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0]); v=body.get('version')
    if v!=p.version:raise HTTPException(409,'项目已经被其他审核员修改，请刷新')
    config=dict(p.config or {})
    if 'name' in body:p.name=str(body['name']).strip()[:200]
    for k in ('s','a','g'):
        if k in body:
            value=int(body[k]);
            if value not in (2,3,4):raise HTTPException(422,'当前知识库仅支持2至4级')
            config[k]=value
    if config.get('g')!=max(config.get('s',3),config.get('a',3)):
        raise HTTPException(422,'依据附录A，G等级应为S与A等级中较高者')
    mapping=next((k for k in knowledge_rows(db) if k['family']=='mapping'),None)
    if mapping and {'s':config['s'],'a':config['a'],'g':config['g']} not in mapping['content'].get('profiles',[]):
        raise HTTPException(422,'该S/A/G组合不在已发布的附录A等级映射中')
    if 'extensions' in body:
        ext=body['extensions']
        if not isinstance(ext,list) or any(x not in ('cloud','mobile','iot','ics','power','bigdata') for x in ext):raise HTTPException(422,'扩展类型无效')
        config['extensions']=list(dict.fromkeys(ext))
    for k in ('aliases','matches'):
        if k in body:
            if not isinstance(body[k],dict):raise HTTPException(422,f'{k} 应为对象')
            config[k]=body[k]
    p.config=config;p.version+=1;audit(db,auth[0],'project_updated',pid);db.commit();return public(p)


@app.post('/api/projects/{pid}/members')
def add_member(pid:str,body:dict,auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0])
    if not auth[0].admin and p.owner_id!=auth[0].id:raise HTTPException(403,'只有项目负责人可添加成员')
    user=db.scalar(select(User).where(User.username==body.get('username')))
    if not user:raise HTTPException(404,'用户不存在')
    if not db.scalar(select(Member.id).where(Member.project_id==pid,Member.user_id==user.id)):
        db.add(Member(project_id=pid,user_id=user.id,role='reviewer'))
    audit(db,auth[0],'member_added',pid,username=user.username);db.commit();return {'ok':True}


async def office_bytes(file:UploadFile, suffix:str):
    name=Path(file.filename or '').name
    if not name.lower().endswith(suffix):raise HTTPException(422,f'只接收{suffix}文件')
    data=await file.read(100*1024*1024+1)
    if len(data)>100*1024*1024:raise HTTPException(413,'文件超过100MB')
    return name,data


def latest_documents(db,pid):
    rows=db.scalars(select(Document).where(Document.project_id==pid).order_by(Document.version.desc())).all()
    return {x.role:x for x in rows[::-1]}


@app.get('/api/projects/{pid}/documents')
def documents(pid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0])
    return [public(x,('parsed','storage_key')) | {'counts':x.parsed.get('counts',{}),'diagnostics':x.parsed.get('diagnostics',[])} for x in db.scalars(select(Document).where(Document.project_id==pid).order_by(Document.created_at.desc()))]


@app.post('/api/projects/{pid}/documents')
async def upload_document(pid:str,role:str=Form(...),file:UploadFile=File(...),auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0])
    if role not in ROLES:raise HTTPException(422,'文档类型无效')
    name,data=await office_bytes(file,'.docx')
    try: parsed=parse_docx(data,role)
    except Exception as exc:raise HTTPException(422,f'文档解析失败：{str(exc)[:200]}') from exc
    version=max([x.version for x in db.scalars(select(Document).where(Document.project_id==pid,Document.role==role))],default=0)+1
    key=uuid.uuid4().hex+'.docx'; folder=DATA/'uploads';folder.mkdir(exist_ok=True)
    (folder/key).write_bytes(data)
    row=Document(project_id=pid,role=role,filename=name,sha256=hashlib.sha256(data).hexdigest(),storage_key=key,version=version,status='partial' if parsed['diagnostics'] else 'parsed',parsed=parsed)
    db.add(row);audit(db,auth[0],'document_uploaded',pid,role=role,version=version,sha256=row.sha256);db.commit()
    return public(row,('parsed','storage_key')) | {'counts':parsed['counts'],'diagnostics':parsed['diagnostics']}


@app.get('/api/projects/{pid}/facts')
def facts(pid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]); docs=latest_documents(db,pid)
    return {role:{'status':d.status,'facts':d.parsed.get('facts',{}),'counts':d.parsed.get('counts',{}),'diagnostics':d.parsed.get('diagnostics',[]),'sections':d.parsed.get('sections',[])} for role,d in docs.items()}


@app.get('/api/projects/{pid}/assets')
def assets(pid:str,scope:str='full',auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0]); docs=latest_documents(db,pid)
    if scope not in ('full','sample'):raise HTTPException(422,'范围无效')
    try:return compare_assets({k:{'id':v.id,'status':v.status,'parsed':v.parsed} for k,v in docs.items()},scope,(p.config or {}).get('aliases'))
    except ValueError as exc:return {'scope':scope,'rows':[],'issues':[],'blocked':str(exc)}


def knowledge_rows(db):
    rows=db.scalars(select(Knowledge).where(Knowledge.status=='published').order_by(Knowledge.created_at.desc())).all()
    selected={}
    for k in rows:
        key=(k.family,k.level,k.profile)
        if key not in selected:selected[key]=k
    return [public(k,('content',)) | {'content':k.content} for k in selected.values()]


@app.get('/api/knowledge')
def knowledge(auth=Depends(current),db=Depends(db_session)):
    return [public(k,('content',)) | {'count':len(k.content.get('requirements',[])),'warnings':k.content.get('warnings',[])} for k in db.scalars(select(Knowledge).order_by(Knowledge.created_at.desc()))]


@app.post('/api/knowledge')
async def upload_knowledge(file:UploadFile=File(...),user=Depends(admin),db=Depends(db_session)):
    name,data=await office_bytes(file,'.xlsx'); sha=hashlib.sha256(data).hexdigest()
    existing=db.scalar(select(Knowledge).where(Knowledge.sha256==sha))
    if existing:return public(existing,('content',)) | {'count':len(existing.content.get('requirements',[])),'warnings':existing.content.get('warnings',[])}
    try:content=import_workbook(data,name)
    except Exception as exc:raise HTTPException(422,f'核查点文件解析失败：{str(exc)[:200]}') from exc
    k=Knowledge(filename=name,sha256=sha,family=content['family'],level=content['level'],profile=content['profile'],content=content,status='draft')
    db.add(k);audit(db,user,'knowledge_uploaded',filename=name,sha256=sha);db.commit()
    return public(k,('content',)) | {'count':len(content.get('requirements',[])),'warnings':content.get('warnings',[])}


@app.post('/api/knowledge/{kid}/publish')
def publish_knowledge(kid:str,user=Depends(admin),db=Depends(db_session)):
    k=db.get(Knowledge,kid)
    if not k:raise HTTPException(404,'依据不存在')
    if k.family!='mapping' and not k.content.get('requirements'):raise HTTPException(422,'依据无有效条目')
    k.status='published';k.published_by=user.id;audit(db,user,'knowledge_published',family=k.family,sha256=k.sha256);db.commit()
    return {'ok':True}


@app.get('/api/projects/{pid}/requirements')
def requirements(pid:str,auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0]); reqs=select_requirements(knowledge_rows(db),p.config or {})
    return {'summary':selection_summary(reqs),'items':reqs}


@app.get('/api/projects/{pid}/records')
def records(pid:str,auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0]); docs=latest_documents(db,pid); report=docs.get('report')
    if not report:return {'items':[],'blocked':'请先上传测评报告'}
    reqs=select_requirements(knowledge_rows(db),p.config or {}); overrides=(p.config or {}).get('matches',{})
    return {'items':[{'record':r,'match_key':f'{report.id}:{r["id"]}','match':match_requirement(r,reqs,overrides.get(f'{report.id}:{r["id"]}'))} for r in report.parsed.get('records',[])], 'count':len(report.parsed.get('records',[]))}


@app.get('/api/model')
def get_model(user=Depends(admin),db=Depends(db_session)):
    m=db.scalar(select(ModelConfig).order_by(ModelConfig.created_at.desc()))
    return {'configured':bool(m),'base_url':m.base_url if m else '', 'model':m.model if m else '', 'external':m.external if m else False,'enabled':m.enabled if m else False,'timeout':m.timeout if m else 120,'has_key':bool(m.key_encrypted) if m else False}


@app.put('/api/model')
def put_model(body:dict,user=Depends(admin),db=Depends(db_session)):
    url=str(body.get('base_url','')).strip(); parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422,'模型地址必须为完整 HTTP(S) 地址，不得包含凭据或查询参数')
    try: private_host=ipaddress.ip_address(parsed.hostname).is_private
    except ValueError: private_host=bool(parsed.hostname and ('.' not in parsed.hostname or parsed.hostname.endswith(('.local','.internal'))))
    if not body.get('external') and parsed.hostname!='localhost' and not private_host:
        raise HTTPException(422,'外部模型请明确勾选“允许发送文档内容到外部服务”')
    name=str(body.get('model','')).strip()
    if not name:raise HTTPException(422,'模型名称不能为空')
    m=db.scalar(select(ModelConfig).order_by(ModelConfig.created_at.desc()))
    if not m:m=ModelConfig(base_url=url,model=name);db.add(m)
    m.base_url=url;m.model=name;m.external=bool(body.get('external'));m.enabled=bool(body.get('enabled',True));m.timeout=min(max(int(body.get('timeout',120)),10),300)
    if body.get('api_key'):m.key_encrypted=Fernet(master_key()).encrypt(str(body['api_key']).encode()).decode()
    audit(db,user,'model_config_updated',external=m.external,host=parsed.hostname);db.commit()
    return get_model(user,db)


def precheck(db,pid,modules):
    docs=latest_documents(db,pid); p=db.get(Project,pid); blockers=[]; counts={}
    for role in ('survey','plan','report'):
        counts[role]=docs[role].parsed.get('counts',{}) if role in docs else None
    if any(m in modules for m in ('assets_full','assets_sample')):
        for module,scope in [('assets_full','full'),('assets_sample','sample')]:
            if module not in modules:continue
            try:compare_assets({k:{'id':v.id,'status':v.status,'parsed':v.parsed} for k,v in docs.items()},scope,(p.config or {}).get('aliases'))
            except ValueError as exc:blockers.append(f'{module}：{exc}')
    reqs=select_requirements(knowledge_rows(db),p.config or {})
    if 'appendix_d' in modules:
        report=docs.get('report')
        if not report or not report.parsed.get('records'):blockers.append('附录D：尚未识别结果记录')
        if not reqs:blockers.append('附录D：当前等级和扩展未选出核查点')
        model=db.scalar(select(ModelConfig).where(ModelConfig.enabled==True).order_by(ModelConfig.created_at.desc()))
        if not model:blockers.append('附录D：管理员尚未配置并启用模型')
    if 'high_risk' in modules:
        report=docs.get('report')
        if not report or not report.parsed.get('risk_tables'):blockers.append('高风险：未识别报告中的问题、整体测评或风险表')
        if not any(k['family']=='high_risk' for k in knowledge_rows(db)):blockers.append('高风险：尚未发布判定指引')
    return {'blockers':blockers,'counts':counts,'requirements':selection_summary(reqs)}


@app.post('/api/projects/{pid}/precheck')
def check_run(pid:str,body:dict,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]); modules=body.get('modules',[])
    if not modules or any(m not in MODULES for m in modules):raise HTTPException(422,'审核模块无效')
    return precheck(db,pid,modules)


@app.post('/api/projects/{pid}/runs')
def start_run(pid:str,body:dict,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);modules=body.get('modules',[])
    if not modules or any(m not in MODULES for m in modules):raise HTTPException(422,'审核模块无效')
    mode=body.get('mode','lenient')
    if mode not in ('lenient','strict'):raise HTTPException(422,'审核模式无效')
    request_key=str(body.get('request_key') or uuid.uuid4())[:100]
    existing=db.scalar(select(Run).where(Run.project_id==pid,Run.request_key==request_key))
    if existing:return public(existing)
    check=precheck(db,pid,modules)
    if check['blockers']:raise HTTPException(422,{'blockers':check['blockers']})
    p=db.get(Project,pid);docs=latest_documents(db,pid);ks=knowledge_rows(db)
    reqs=select_requirements(ks,p.config or {})
    model=db.scalar(select(ModelConfig).where(ModelConfig.enabled==True).order_by(ModelConfig.created_at.desc()))
    snapshot={'project_config':p.config,'document_ids':{r:d.id for r,d in docs.items()},'knowledge_ids':list({r['knowledge_id'] for r in reqs}),
              'guide_ids':[k['id'] for k in ks if k['family']=='high_risk'],'model_id':model.id if model else None,'created_by':auth[0].id}
    run=Run(project_id=pid,request_key=request_key,mode=mode,modules=modules,snapshot=snapshot,status='queued')
    db.add(run);db.flush()
    def task(kind,label,payload):db.add(Task(project_id=pid,run_id=run.id,kind=kind,label=label,payload=payload,status='queued'))
    if 'assets_full' in modules:task('assets','三文档完整资产核查',{'scope':'full'})
    if 'assets_sample' in modules:task('assets','方案与报告抽选对象核查',{'scope':'sample'})
    if 'high_risk' in modules:task('risk','高风险表格交叉核查',{})
    if 'appendix_d' in modules:
        report=docs['report'];overrides=(p.config or {}).get('matches',{})
        for rec in report.parsed['records']:
            match=match_requirement(rec,reqs,overrides.get(f'{report.id}:{rec["id"]}'))
            task('record',f'{rec["object"]} · {rec["source"]}',{'record_id':rec['id'],'requirement_key':match['requirement']['key'] if match['status']=='matched' else None,'match_status':match['status']})
    audit(db,auth[0],'run_started',pid,run_id=run.id,modules=modules,mode=mode);db.commit()
    for _ in range(4):POOL.submit(drain_tasks)
    return public(run)


@app.get('/api/projects/{pid}/runs')
def runs(pid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);rows=db.scalars(select(Run).where(Run.project_id==pid).order_by(Run.created_at.desc())).all()
    return [{**public(r),'tasks':dict(Counter(t.status for t in db.scalars(select(Task).where(Task.run_id==r.id))))} for r in rows]


@app.get('/api/projects/{pid}/runs/{rid}')
def run_detail(pid:str,rid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);r=db.get(Run,rid)
    if not r or r.project_id!=pid:raise HTTPException(404,'任务不存在')
    return {'run':public(r),'tasks':[public(t) for t in db.scalars(select(Task).where(Task.run_id==rid).order_by(Task.created_at))]}


@app.post('/api/projects/{pid}/runs/{rid}/cancel')
def cancel_run(pid:str,rid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);r=db.get(Run,rid)
    if not r or r.project_id!=pid:raise HTTPException(404,'任务不存在')
    r.cancelled=True;r.status='cancelled'
    for t in db.scalars(select(Task).where(Task.run_id==rid,Task.status=='queued')):t.status='cancelled'
    audit(db,auth[0],'run_cancelled',pid,run_id=rid);db.commit();return {'ok':True}


@app.post('/api/projects/{pid}/tasks/{tid}/retry')
def retry_task(pid:str,tid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);t=db.get(Task,tid)
    if not t or t.project_id!=pid:raise HTTPException(404,'子任务不存在')
    if t.status not in ('failed','blocked'):raise HTTPException(409,'仅失败或待确认任务可重试')
    r=db.get(Run,t.run_id)
    if t.kind=='record' and not t.payload.get('requirement_key'):
        report_id=r.snapshot['document_ids']['report']
        override=(db.get(Project,pid).config or {}).get('matches',{}).get(f'{report_id}:{t.payload["record_id"]}')
        allowed={x['key'] for kid in r.snapshot['knowledge_ids'] for x in db.get(Knowledge,kid).content.get('requirements',[])}
        if not override or override not in allowed:raise HTTPException(422,'请先在附录D界面确认该条结果记录对应的测评项')
        t.payload={**t.payload,'requirement_key':override,'match_status':'manual_at_retry'}
    t.status='queued';t.error='';t.lease='';t.lease_until=0
    r.status='queued';audit(db,auth[0],'task_retried',pid,task_id=tid);db.commit();POOL.submit(drain_tasks)
    return {'ok':True}


def claim_task(db):
    # ponytail: SQLite is a one-process local demo; PostgreSQL also supports row locks.
    for _ in range(8):
        now=time.time();token=uuid.uuid4().hex
        condition=(Task.status=='queued') | ((Task.status=='running') & (Task.lease_until<now))
        stmt=select(Task).where(condition).order_by(Task.created_at).limit(1)
        if not str(engine.url).startswith('sqlite'):stmt=stmt.with_for_update(skip_locked=True)
        t=db.scalar(stmt)
        if not t:return None
        r=db.get(Run,t.run_id)
        if r.cancelled:t.status='cancelled';db.commit();continue
        changed=db.execute(update(Task).where(Task.id==t.id,condition).values(status='running',lease=token,lease_until=now+360,attempts=Task.attempts+1))
        if changed.rowcount!=1:db.rollback();continue
        r.status='running';db.commit();return t.id,token
    return None


def recover_tasks():
    with Session() as db:
        for t in db.scalars(select(Task).where(Task.status=='running',Task.lease_until<time.time())):
            t.status='queued';t.lease='';t.lease_until=0
        db.commit()
    drain_tasks()


def drain_tasks():
    while True:
        with Session() as db:claimed=claim_task(db)
        if not claimed:return
        tid,token=claimed
        try:
            with Session() as db:
                t=db.get(Task,tid);result=perform_task(db,t)
                r=db.get(Run,t.run_id)
                if r.cancelled:status='cancelled';result={'issues':[],'output':{}}
                else:status=result.get('status','done')
                if t.lease!=token:continue
                for item in result.get('issues',[]):
                    db.add(Issue(project_id=t.project_id,run_id=t.run_id,task_id=t.id,**item))
                t.output=result.get('output',{});t.status=status;t.finished_at=time.time();t.lease='';t.lease_until=0
                remaining=db.scalars(select(Task).where(Task.run_id==r.id,Task.id!=tid)).all()
                states=[x.status for x in remaining]+[status]
                if all(x in ('done','blocked','failed','cancelled') for x in states):
                    r.status='cancelled' if r.cancelled else ('partial' if any(x in ('blocked','failed') for x in states) else 'done')
                db.commit()
        except Exception as exc:
            with Session() as db:
                t=db.get(Task,tid)
                if t and t.lease==token:
                    t.status='failed';t.error=str(exc)[:400];t.finished_at=time.time();t.lease='';t.lease_until=0
                    r=db.get(Run,t.run_id);r.status='partial';db.commit()


def perform_task(db,t):
    r=db.get(Run,t.run_id);snap=r.snapshot
    docs={role:db.get(Document,did) for role,did in snap['document_ids'].items()}
    if t.kind=='assets':
        result=compare_assets({k:{'id':v.id,'status':v.status,'parsed':v.parsed} for k,v in docs.items()},t.payload['scope'],snap['project_config'].get('aliases'))
        return {'issues':result['issues'],'output':{'rows':result['rows'],'scope':result['scope']}}
    if t.kind=='risk':
        guide=[row for kid in snap['guide_ids'] for row in db.get(Knowledge,kid).content.get('requirements',[])]
        result=risk_review(docs['report'].parsed,guide)
        return {'issues':result['issues'],'output':result}
    record=next(x for x in docs['report'].parsed['records'] if x['id']==t.payload['record_id'])
    reqkey=t.payload.get('requirement_key')
    if not reqkey:return {'status':'blocked','output':{'reason':'测评项未能唯一匹配；请人工确认后重试','record':record}}
    req=next((x for kid in snap['knowledge_ids'] for x in db.get(Knowledge,kid).content['requirements'] if x['key']==reqkey),None)
    if not req:return {'status':'blocked','output':{'reason':'核查点版本中未找到测评项','record':record}}
    model=db.get(ModelConfig,snap['model_id'])
    if not model or not model.enabled:return {'status':'blocked','output':{'reason':'模型配置不可用'}}
    key=Fernet(master_key()).decrypt(model.key_encrypted.encode()).decode() if model.key_encrypted else ''
    analysis=evaluate(record,req,r.mode,public(model,('key_encrypted',)),key)
    evidence=[{'role':'report','source':record['source'],'quote':record['text']},
              {'role':'knowledge','source':req['source'],'quote':req['text']},
              {'role':'knowledge','source':req['source']+' · 判定规则','quote':req.get('decision') or '来源未提供判定规则'}]
    issues=[]
    for point in analysis['point_results']:
        if point['coverage']=='covered':continue
        text=next(p['text'] for p in req['points'] if p['id']==point['point_id'])
        issues.append(issue('APP_D','description_coverage','核查点描述需复核',f'{text}：{point.get("reason","")}','补充真实测评事实或确认该核查点不适用。',record['object'],evidence+[{'role':'knowledge','source':req['source']+' · 核查点','quote':text}],record_id=record['id'],point_id=point['point_id'],mode=r.mode,coverage=point['coverage']))
    verdict=analysis['verdict_review']
    if verdict['status']=='contradicted':
        issues.append(issue('APP_D','verdict','符合情况与结果记录不一致',verdict['reason'],'核对判定规则和实际证据后修正符合情况。',record['object'],evidence,record_id=record['id'],original_verdict=record['verdict']))
    for item in analysis['writing']:
        issues.append(issue('APP_D','writing','结果记录文字需修改',item['quote'],item['suggestion'],record['object'],evidence,record_id=record['id'],writing_type=item['type']))
    return {'issues':issues,'output':{'record':record,'requirement':req,'analysis':analysis}}


@app.get('/api/chapters')
def chapters(auth=Depends(current)):
    return [{'code':code,'title':title,'configured':code in ('ALL','CROSS_DOCUMENT','APP_D','CH05','MAJOR_HAZARD')} for code,title in CHAPTERS]


@app.get('/api/projects/{pid}/issues')
def issues(pid:str,chapter:str='ALL',status:str='',run_id:str='',auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);stmt=select(Issue).where(Issue.project_id==pid)
    if chapter!='ALL':stmt=stmt.where(Issue.chapter==chapter)
    if status:stmt=stmt.where(Issue.status==status)
    if run_id:stmt=stmt.where(Issue.run_id==run_id)
    return [public(x) for x in db.scalars(stmt.order_by(Issue.created_at.desc()))]


@app.patch('/api/projects/{pid}/issues/{iid}')
def review_issue(pid:str,iid:str,body:dict,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0]);row=db.get(Issue,iid)
    if not row or row.project_id!=pid:raise HTTPException(404,'问题不存在')
    if row.version!=body.get('version'):raise HTTPException(409,'问题已被其他审核员修改，请刷新')
    status=body.get('status',row.status)
    if status not in ('pending','confirmed','rejected','needs_evidence','resolved'):raise HTTPException(422,'复核状态无效')
    row.status=status;row.note=str(body.get('note',row.note))[:4000];row.version+=1
    audit(db,auth[0],'issue_reviewed',pid,issue_id=iid,status=status);db.commit();return public(row)


@app.get('/api/projects/{pid}/risk')
def risk_output(pid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0])
    tasks=db.scalars(select(Task).where(Task.project_id==pid,Task.kind=='risk',Task.status=='done').order_by(Task.finished_at.desc())).all()
    return tasks[0].output if tasks else {'candidates':[],'linked_rows':[],'note':'尚未运行高风险核查'}


@app.get('/api/projects/{pid}/export')
def export_issues(pid:str,format:str='xlsx',auth=Depends(current),db=Depends(db_session)):
    p=project_access(db,pid,auth[0]);rows=db.scalars(select(Issue).where(Issue.project_id==pid,Issue.status=='confirmed').order_by(Issue.chapter,Issue.created_at)).all()
    headers=['章节','问题类别','问题标题','问题说明','修改建议','关联对象','原文位置','复核意见']
    values=[[x.chapter,x.category,x.title,x.description,x.suggestion,x.object_name,'；'.join(e.get('source','') for e in x.evidence),x.note] for x in rows]
    if format=='xlsx':
        book=Workbook();sheet=book.active;sheet.title='已确认问题';sheet.append(headers)
        # Imported report text must stay text when opened in Excel.
        for row in values:sheet.append([("'"+str(v) if str(v).startswith(('=','+','-','@')) else str(v)) for v in row])
        for col,width in {'A':18,'B':22,'C':32,'D':60,'E':60,'F':28,'G':46,'H':40}.items():sheet.column_dimensions[col].width=width
        stream=io.BytesIO();book.save(stream);media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';suffix='xlsx'
    elif format=='docx':
        book=WordDocument();book.add_heading('等保测评报告审核问题汇总',0);book.add_paragraph(f'项目：{p.name}；仅导出人工确认的问题。')
        for i,row in enumerate(values,1):
            book.add_heading(f'{i}. {row[2]}',level=2)
            for name,val in zip(headers,row):book.add_paragraph(f'{name}：{val}')
        stream=io.BytesIO();book.save(stream);media='application/vnd.openxmlformats-officedocument.wordprocessingml.document';suffix='docx'
    else:raise HTTPException(422,'仅支持xlsx或docx')
    stream.seek(0);audit(db,auth[0],'issues_exported',pid,format=format,count=len(rows));db.commit()
    return StreamingResponse(stream,media_type=media,headers={'Content-Disposition':f'attachment; filename="review-issues.{suffix}"'})


@app.get('/api/projects/{pid}/audit')
def audit_log(pid:str,auth=Depends(current),db=Depends(db_session)):
    project_access(db,pid,auth[0])
    return [public(x) for x in db.scalars(select(Audit).where(Audit.project_id==pid).order_by(Audit.created_at.desc()).limit(200))]


DIST = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')


@app.get('/')
@app.get('/{path:path}')
def frontend(path:str=''):
    if path.startswith('api/'):raise HTTPException(404,'接口不存在')
    if not DIST.exists():return {'message':'前端尚未构建，请在 frontend 执行 npm run build'}
    return FileResponse(DIST/'index.html')

