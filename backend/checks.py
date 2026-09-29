"""Deterministic checks produce evidence-backed candidates, never silent truth overrides."""
import re
from collections import defaultdict
from difflib import SequenceMatcher

from .catalog import norm


def field_norm(key,value):
    text=norm(value)
    if 'ip' in norm(key):
        return tuple(sorted(set(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?|[a-fA-F\d:]{3,}:[a-fA-F\d:]*',str(value))))) or text
    return text


def canonical_field(key):
    value=norm(key)
    for words,name in [(['ip地址','ip'],'ip'),(['品牌','型号'],'brand_model'),(['操作系统','系统及版本','系统/版本'],'system_version'),(['物理位置'],'location'),(['重要程度'],'importance'),(['用途','主要功能'],'purpose'),(['虚拟设备'],'virtual'),(['数量'],'quantity')]:
        if any(x in value for x in words):return name
    return value


def issue(chapter,category,title,description,suggestion,obj='',evidence=None,**more):
    return {'chapter':chapter,'category':category,'title':title,'description':description,'suggestion':suggestion,'object_name':obj,'evidence':evidence or [],'machine':more}


def compare_assets(documents, scope='full', aliases=None):
    roles=['survey','plan','report'] if scope=='full' else ['plan','report']
    groups=defaultdict(lambda:defaultdict(list)); issues=[]; rows=[]
    aliases=aliases or {}
    for role in roles:
        doc=documents.get(role)
        if not doc or doc.get('status') not in ['parsed','partial']: raise ValueError('需要所选范围的所有文档解析成功')
        items=[a for a in doc['parsed']['assets'] if a['scope']==('full' if scope=='full' else ('planned_sample' if role=='plan' else 'actual_sample'))]
        if not items: raise ValueError(f'{role} 未识别到{scope}清单，先确认表格范围；不能把未解析当资产缺失')
        for a in items:
            alias_key=f'{role}:{doc.get("id", "")}:{a["id"]}' if doc.get('id') else f'{role}:{a["id"]}'
            name=aliases.get(alias_key,a['name'])
            a={**a,'alias_key':alias_key}
            groups[(a['type'],norm(name))][role].append(a)
    for (kind,key),by_role in groups.items():
        name=next(iter(by_role.values()))[0]['name']
        ev=[{'role':role,'quote':a['name']+' '+str(a['attributes']),'source':a['source']} for role,vals in by_role.items() for a in vals]
        status='consistent'; differences=[]
        if any(len(v)>1 for v in by_role.values()):
            status='ambiguous';issues.append(issue('CROSS_DOCUMENT','asset_match','同名对象需要确认',f'{name} 在同一来源中出现多次，未自动合并。','核对对象身份、表格范围和重复记录。',name,ev))
        elif len(by_role)<len(roles):
            status='missing'; missing=[r for r in roles if r not in by_role]
            issues.append(issue('CROSS_DOCUMENT','asset_missing','对象未在全部对照来源中找到',f'{name} 未在 {", ".join(missing)} 的指定清单中匹配到。','先确认别名或合法变更；不能默认报告为正确值。',name,ev))
        else:
            attrs={r:{canonical_field(k):v for k,v in vals[0]['attributes'].items()} for r,vals in by_role.items()}
            field_keys=set.intersection(*(set(x) for x in attrs.values()))
            for f in sorted(field_keys):
                values={r:attrs[r][f] for r in roles}
                if len({str(field_norm(f,v)) for v in values.values()})>1:
                    differences.append({'field':f,'values':values})
            if differences:
                status='different';issues.append(issue('CROSS_DOCUMENT','asset_difference',f'{name} 存在属性差异','；'.join(d['field'] for d in differences),'并列核对原始值；自由文本差异需审核员确认语义。',name,ev,differences=differences))
        rows.append({'name':name,'type':kind,'status':status,'sources':dict(by_role),'differences':differences})
    return {'rows':rows,'issues':issues,'scope':scope}


def match_requirement(record, requirements, override=None):
    if override:
        found=[r for r in requirements if r['key']==override]
        return {'status':'matched','requirement':found[0],'method':'manual'} if len(found)==1 else {'status':'unmatched','candidates':[]}
    pool=[r for r in requirements if r['domain']==record['domain'] and r['family']==record['extension']]
    def clean(t):
        return re.sub(r'[^\w\u4e00-\u9fff]','',norm(t).replace('测评指标',''))
    target=clean(record['requirement'])
    exact=[r for r in pool if clean(r['text'])==target]
    if len(exact)==1: return {'status':'matched','requirement':exact[0],'method':'exact'}
    ranked=sorted([{'key':r['key'],'text':r['text'],'source':r['source'],'score':round(SequenceMatcher(None,target,clean(r['text'])).ratio(),3)} for r in pool],key=lambda r:r['score'],reverse=True)[:3]
    # ponytail: fuzzy matches are suggestions; reviewers confirm before model calls.
    return {'status':'ambiguous' if ranked else 'unmatched','candidates':ranked}


def risk_review(parsed, guide):
    candidates=[];issues=[]; linked=[]
    for table in parsed.get('risk_tables',[]):
        headers=table['headers']
        for i,row in enumerate(table['rows']):
            values={h:row[j] for j,h in enumerate(headers) if j<len(row) and h}
            text=' '.join(row)
            if not text.strip(): continue
            description=next((v for k,v in values.items() if '问题' in k and '分析' not in k and '编号' not in k),'')
            if not description: continue
            obj=next((v for k,v in values.items() if '对象' in k or '关联资产' in k),'')
            source=f'{table["source"]} · 数据行{i+1}'
            linked.append({'kind':table['kind'],'description':description,'object':obj,'source':source,'values':values})
            if table['kind']=='risk':
                analysis=next((v for k,v in values.items() if '风险分析' in k or '危害分析' in k),'')
                grade=next((v for k,v in values.items() if '风险等级' in k or k.strip()=='风险程度'),'')
                stated=re.search(r'(?:故判为|判定为|判为)\s*([高中低])风险',analysis)
                if stated and grade and stated[1] not in grade:
                    issues.append(issue('CH05','risk_consistency','风险分析与风险等级不一致',f'分析文字为“{stated[1]}风险”，等级列为“{grade}”。','核实正确结论后统一文字、等级和关联汇总。',obj,[{'source':source,'quote':analysis},{'source':source,'quote':grade}]))
            if table['kind']=='problem':
                ranking=[]
                for rule in guide:
                    score=SequenceMatcher(None,norm(description),norm(rule.get('scenario',''))).ratio()
                    if score>=0.3: ranking.append({**rule,'score':round(score,3)})
                ranking.sort(key=lambda x:x['score'],reverse=True)
                candidates.append({'description':description,'object':obj,'source':source,'matches':ranking[:3],'status':'candidate' if ranking else 'unmatched','major_hazard_assessment':'pending'})
                evidence=[{'role':'report','source':source,'quote':description}]
                evidence += [{'role':'knowledge','source':x['source'],'quote':x['scenario']} for x in ranking[:3]]
                issues.append(issue('MAJOR_HAZARD','high_risk_screening','高风险判定待人工核对',
                                    description,'核对指引条件、缓解措施、整体测评和风险分析后记录是否成立。',obj,
                                    evidence,guide_candidates=[{'key':x['key'],'source':x['source'],'score':x['score']} for x in ranking[:3]],auto_conclusion='none'))
            if table['kind']=='hazard':
                issues.append(issue('MAJOR_HAZARD','major_hazard_table','重大风险隐患表需与问题核对',
                                    description,'核对触发项是否有对应的报告证据和风险分析。',obj,
                                    [{'role':'report','source':source,'quote':description}],auto_conclusion='none'))
    if not linked: raise ValueError('未识别到安全问题/整体测评/风险分析表，不能视为无高风险问题')
    for candidate in candidates:
        # A description match alone is not enough to merge different assets.
        candidate['related']=[x for x in linked if x['kind']!='problem' and norm(x['description'])==norm(candidate['description']) and (not candidate['object'] or not x['object'] or norm(x['object'])==norm(candidate['object']))]
    return {'candidates':candidates,'issues':issues,'linked_rows':linked,'guide_available':bool(guide),'note':'指引匹配为候选，未自动判定高风险或重大隐患成立。'}

