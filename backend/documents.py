"""Read DOCX in document order and keep a locator for every extracted value."""
import hashlib
import re
from io import BytesIO

from docx import Document as WordDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from .catalog import norm, safe_zip

DOMAINS = ['安全物理环境','安全通信网络','安全区域边界','安全计算环境','安全管理中心','安全管理制度','安全管理机构','安全管理人员','安全建设管理','安全运维管理']
CHAPTERS = [('ALL','全部问题'),('CROSS_DOCUMENT','跨文档一致性'),('FULL_TEXT','全文 / 规范性'),('BASIC_INFO','基本信息表'),('CONCLUSION','结论页'),('MAJOR_HAZARD','重大风险隐患')] + [(f'CH{i:02}',f'第{i}章') for i in range(1,9)] + [(f'APP_{x}',f'附录{x}') for x in 'ABCDEFGH'] + [('OTHER','其他')]
TYPE_NAMES = {'room':'物理机房','network_device':'网络设备','security_device':'安全设备','server':'服务器','terminal':'终端设备','other':'其他系统或设备','software':'系统管理软件/平台','application':'业务应用系统/平台','data':'数据资源','crypto_product':'密码产品','person':'安全管理人员','document':'安全管理文档'}
NAME_HEADERS = ['机房名称','设备名称','产品/模块名称','系统管理软件/平台名称','业务应用系统/平台名称','文档名称','姓名','数据类别','应用名称','系统名称']


def header_key(text):
    return norm(text).replace(' ','').replace('（','(').replace('）',')')


def chapter_for(text, style, current):
    t=norm(text)
    if 'toc' in style.lower() or '目录' in style or '……' in text: return current
    explicit=re.match(r'附录([a-h])',t)
    if explicit: return 'APP_'+explicit[1].upper()
    if '单项测评结果记录' == t: return 'APP_D'
    if '测评对象资产' in t and ('标题' in style or 'Heading' in style): return 'APP_A'
    if '标题' in style or 'Heading' in style:
        for k,v in [('单项测评结果分析','CH03'),('整体测评','CH04'),('风险分析','CH05'),('安全问题风险分析','CH05'),('等级测评结论','CONCLUSION'),('基本信息','BASIC_INFO')]:
            if t==norm(k): return v
        m=re.match(r'([1-8])(?:[.、\s]|[^\d])',text.strip())
        if m and not text.strip().startswith(tuple(f'{i}.' for i in range(1,9))): return f'CH{int(m[1]):02}'
    return current


def asset_type(headers, context):
    for word,kind in [('物理机房','room'),('机房','room'),('网络设备','network_device'),('安全设备','security_device'),('服务器','server'),('终端设备','terminal'),('其他设备','other'),('系统管理软件','software'),('业务应用','application'),('数据资源','data'),('密码产品','crypto_product'),('安全相关人员','person'),('安全管理文档','document')]:
        if word in context:return kind
    full=' '.join(headers)
    for word,kind in [('机房名称','room'),('产品/模块名称','crypto_product'),('文档名称','document'),('姓名','person'),('数据类别','data'),('系统管理软件/平台名称','software'),('业务应用系统/平台名称','application')]:
        if word in full:return kind
    return 'other'


def parse_docx(data, role):
    safe_zip(data,'word/document.xml')
    doc=WordDocument(BytesIO(data))
    result={'sections':[],'assets':[],'records':[],'risk_tables':[],'diagnostics':[],'facts':{},'tables':0}
    chapter='OTHER'; domain=''; extension='general'; object_name=''; recent=[]; ordinal=0
    for element in doc.element.body:
        if element.tag.endswith('}p'):
            p=Paragraph(element,doc); text=p.text.strip()
            if not text: continue
            style=p.style.name if p.style else ''
            if 'toc' in style.lower() or '目录' in style: continue
            old=chapter; chapter=chapter_for(text,style,chapter)
            if chapter!=old or '标题' in style or 'Heading' in style:
                result['sections'].append({'code':chapter,'title':text,'paragraph':ordinal})
            for name in DOMAINS:
                if norm(text).endswith(norm(name)) and len(text)<35:
                    domain=name; object_name=''; extension='general'; break
            for word,code in [('云计算','cloud'),('移动互联','mobile'),('物联网','iot'),('工业控制','ics'),('电力行标','power'),('大数据','bigdata'),('安全通用要求','general')]:
                if word in text and '要求' in text and len(text)<45:
                    extension=code; object_name=''; break
            if chapter=='APP_D' and ('四级标题' in style or '五级标题' in style or re.match(r'D\.\d+\.\d+\.\d+',text)):
                object_name=text
            recent.append(text); recent=recent[-7:]; ordinal+=1
            continue
        if not element.tag.endswith('}tbl'): continue
        table=Table(element,doc); result['tables']+=1; ti=result['tables']
        rows=[[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows: continue
        caption=recent[-1] if recent else ''
        context=' / '.join(recent[-4:]); location=f'{chapter} · 表{ti}'
        for row in rows:
            joined=' '.join(row)
            matches=re.findall(r'S([1-5])\s*A([1-5])(?:\s*G([1-5]))?',joined)
            if matches:
                result['facts']['profile_candidates']=list({f'S{s}A{a}G{g or max(s,a)}' for s,a,g in matches})
        header_index=None
        for ri,row in enumerate(rows[:6]):
            if any('结果记录' in cell for cell in row) and any('符合' in cell for cell in row): header_index=ri; break
        if header_index is not None:
            headers=rows[header_index]
            idx={}
            for i,h in enumerate(headers):
                for key, words in {'control':['控制点'],'requirement':['测评项','测评指标'],'text':['结果记录'],'verdict':['符合情况','符合程度']}.items():
                    if any(w in h for w in words): idx[key]=i
            if len(idx)!=4:
                result['diagnostics'].append(f'{location}：记录表字段不完整'); continue
            for ri,row in enumerate(rows[header_index+1:],header_index+2):
                vals={k:row[i] if i<len(row) else '' for k,i in idx.items()}
                if not vals['requirement'] or vals['requirement'] in ('测评项','测评指标'): continue
                evidence_id=f't{ti}r{ri}'
                result['records'].append({'id':evidence_id,'chapter':'APP_D','domain':domain,'extension':extension,'object':object_name or domain or '对象待确认','control':vals['control'],'requirement':vals['requirement'],'text':vals['text'],'verdict':vals['verdict'],'source':f'附录D · 表{ti} · 第{ri}行','evidence_id':evidence_id})
            continue
        # Asset inventories have a name column and at least one business attribute.
        for hi,header in enumerate(rows[:5]):
            name_indices=[i for i,h in enumerate(header) if header_key(h) in [header_key(x) for x in NAME_HEADERS]]
            if not name_indices or len(set(header))<3: continue
            ni=name_indices[0]; kind=asset_type(header,caption)
            # The assessment plan has full inventories in tables 2-* and samples in 3-*.
            # Tool inventories in chapter 4 are not assessed assets.
            plan_caption=re.search(r'表\s*([234])\s*[-－]',caption)
            if role=='plan' and (not plan_caption or plan_caption[1]=='4'):
                break
            if role=='report' and chapter not in ('OTHER','APP_A'):
                break
            sample=(role=='plan' and bool(plan_caption and plan_caption[1]=='3')) or (role=='report' and chapter=='OTHER') or ('抽选' in caption or '抽样' in caption or '测评对象选择' in caption or '测评对象选取' in caption)
            scope=('planned_sample' if role=='plan' else 'actual_sample') if sample else 'full'
            for ri,row in enumerate(rows[hi+1:],hi+2):
                if ni>=len(row) or not row[ni] or row[ni] in header or re.match(r'^合计|^总计',row[ni]): continue
                if norm(row[ni]) in ('--','—','不涉及','本次测评不涉及','无','待填写') or 'xxxx' in norm(row[ni]):continue
                attrs={header[i]:v for i,v in enumerate(row) if i<len(header) and header[i] and i!=ni and header[i] not in ['序号','编号']}
                result['assets'].append({'id':f'a{ti}r{ri}','type':kind,'name':row[ni],'scope':scope,'attributes':attrs,'source':f'{location} · 第{ri}行','context':context})
            break
        # Keep all problem tables, not just the first fuzzy match.
        risk_header=None
        for hi,row in enumerate(rows[:5]):
            text=' '.join(row)
            if ('问题' in text and ('风险' in text or '整体测评' in text)) or ('安全问题' in text and ('对象' in text or '测评项' in text)):
                risk_header=hi; break
        if risk_header is not None and chapter in ('CH03','CH04','CH05'):
            header=rows[risk_header]
            kind='risk' if any('风险分析' in h or '风险等级' in h for h in header) else ('overall' if chapter=='CH04' else ('hazard' if any('重大风险隐患' in h for h in header) else 'problem'))
            result['risk_tables'].append({'kind':kind,'chapter':chapter,'source':location,'headers':header,'rows':rows[risk_header+1:]})
    if role=='report' and not result['records']: result['diagnostics'].append('未识别到附录D结果记录；请检查表头和章节结构')
    if not result['assets']: result['diagnostics'].append('未识别到资产清单；不可据此认定不存在资产')
    result['counts']={'assets':len(result['assets']),'records':len(result['records']),'tables':result['tables']}
    return result

