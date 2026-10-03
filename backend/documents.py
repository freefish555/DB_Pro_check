"""Read DOCX in document order and keep a locator for every extracted value."""
import hashlib
import re
from io import BytesIO

from docx import Document as WordDocument
from docx.table import Table
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .catalog import norm, safe_zip

DOMAINS = ['安全物理环境','安全通信网络','安全区域边界','安全计算环境','安全管理中心','安全管理制度','安全管理机构','安全管理人员','安全建设管理','安全运维管理']
CHAPTERS = [('ALL','全部问题'),('CROSS_DOCUMENT','跨文档一致性'),('FULL_TEXT','全文 / 规范性'),('COVER','封面'),('BASIC_INFO','基本信息表'),('STATEMENT','声明'),('CONCLUSION','结论页'),('MAJOR_HAZARD','重大风险隐患'),('RECTIFICATION','整改建议')] + [(f'CH{i:02}',f'第{i}章') for i in range(1,9)] + [(f'APP_{x}',f'附录{x}') for x in 'ABCDEFGH'] + [('OTHER','其他')]
TYPE_NAMES = {'room':'物理机房','network_device':'网络设备','security_device':'安全设备','server':'服务器','terminal':'终端设备','other':'其他系统或设备','software':'系统管理软件/平台','application':'业务应用系统/平台','data':'数据资源','crypto_product':'密码产品','person':'安全管理人员','document':'安全管理文档'}
NAME_HEADERS = ['机房名称','设备名称','产品/模块名称','系统管理软件/平台名称','业务应用系统/平台名称','文档名称','姓名','数据类别','应用名称','系统名称']


def header_key(text):
    return norm(text).replace(' ','').replace('（','(').replace('）',')')


def chapter_for(text, style, current, is_heading=False):
    t=norm(text)
    if 'toc' in style.lower() or '目录' in style or '……' in text: return current
    for title,code in [('等级测评结论','CONCLUSION'),('测评结论','CONCLUSION'),
                       ('基本信息表','BASIC_INFO'),('重大风险隐患','MAJOR_HAZARD'),
                       ('整改建议','RECTIFICATION'),('声明','STATEMENT')]:
        if t==norm(title):return code
    if t.endswith('等级保护测评报告') or t=='测评报告':return 'COVER'
    explicit=re.match(r'附录([a-h])',t)
    if explicit: return 'APP_'+explicit[1].upper()
    if '单项测评结果记录' == t: return 'APP_D'
    is_heading=is_heading or '标题' in style or 'Heading' in style
    if '测评对象资产' in t and is_heading: return 'APP_A'
    if is_heading:
        numbered=re.match(r'(?:第\s*([1-8])\s*章|([1-8])(?:[.、\s]|[^\d]))',text.strip())
        if numbered: return f'CH{int(numbered[1] or numbered[2]):02}'
        for k,v in [('单项测评结果分析','CH03'),('整体测评','CH04'),('风险分析','CH05'),('安全问题风险分析','CH05'),('等级测评结论','CONCLUSION'),('基本信息','BASIC_INFO')]:
            if t==norm(k): return v
    return current


def explicit_number(text):
    match=re.match(r'^\s*(附录\s*[A-H]|第\s*[1-8]\s*章)',text,re.I)
    if not match:match=re.match(r'^\s*([1-8](?:\.\d+)*)(?=\s|[、.．]|$)',text)
    return re.sub(r'\s+','',match[1]) if match else None


def content_references(element, location):
    images=[]
    for drawing in element.xpath('.//w:drawing|.//w:pict'):
        blips=list(drawing.iter(qn('a:blip')))+list(drawing.iter('{urn:schemas-microsoft-com:vml}imagedata'))
        if not blips:continue
        index=len(images)+1
        images.append({'location':f'{location} · 图片{index}',
                       'relationship_id':blips[0].get(qn('r:embed')) or blips[0].get(qn('r:id'))})
    textboxes=[]
    for index,box in enumerate(element.xpath('.//w:txbxContent'),1):
        textboxes.append({'location':f'{location} · 文本框{index}',
                          'text':''.join(node.text or '' for node in box.iter(qn('w:t')))})
    return images,textboxes


def body_elements(body):
    """Unwrap common Word containers without losing body order."""
    for element in body:
        if element.tag in (qn('w:sdt'), qn('w:customXml')):
            content = element.find(qn('w:sdtContent')) if element.tag == qn('w:sdt') else element
            if content is None:
                yield element
            else:
                yield from body_elements(content)
        else:
            yield element


def asset_type(headers, context):
    for word,kind in [('物理机房','room'),('机房','room'),('网络设备','network_device'),('安全设备','security_device'),('服务器','server'),('终端设备','terminal'),('其他设备','other'),('系统管理软件','software'),('业务应用','application'),('数据资源','data'),('密码产品','crypto_product'),('安全相关人员','person'),('安全管理文档','document')]:
        if word in context:return kind
    full=' '.join(headers)
    for word,kind in [('机房名称','room'),('产品/模块名称','crypto_product'),('文档名称','document'),('姓名','person'),('数据类别','data'),('系统管理软件/平台名称','software'),('业务应用系统/平台名称','application')]:
        if word in full:return kind
    return 'other'


def heading_level(paragraph):
    style=paragraph.style
    while style is not None:
        properties=style.element.pPr
        outline=properties.find(qn('w:outlineLvl')) if properties is not None else None
        if outline is not None:
            level=int(outline.get(qn('w:val')))+1
            return level if level<=9 else None
        match=re.search(r'(?:Heading\s*|标题\s*)([1-9])',style.name,re.I)
        if match: return int(match[1])
        style=style.base_style
    return None


class NumberingResolver:
    """Resolve Word heading labels from numbering.xml in document order."""

    def __init__(self, document):
        root=document.part.numbering_part.element
        abstracts={int(x.get(qn('w:abstractNumId'))):x for x in root.findall(qn('w:abstractNum'))}
        self.definitions={}
        for num in root.findall(qn('w:num')):
            reference=num.find(qn('w:abstractNumId'))
            if reference is None:continue
            abstract=abstracts.get(int(reference.get(qn('w:val'))))
            if abstract is None:continue
            levels={}
            for lvl in abstract.findall(qn('w:lvl')):
                index=int(lvl.get(qn('w:ilvl')))
                def value(tag, default=''):
                    node=lvl.find(qn(f'w:{tag}'))
                    return node.get(qn('w:val')) if node is not None else default
                levels[index]={'start':int(value('start','1')),'format':value('numFmt'),
                               'text':value('lvlText'),'style':value('pStyle')}
            self.definitions[int(num.get(qn('w:numId')))]=levels
        self.counters={}

    def label(self, paragraph, fallback_level):
        own=paragraph._p.pPr.numPr if paragraph._p.pPr is not None else None
        num_id=own.numId.val if own is not None and own.numId is not None else None
        level=own.ilvl.val if own is not None and own.ilvl is not None else None
        style=paragraph.style;styles=[]
        while style is not None:
            styles.append(style.style_id)
            style_num=style.element.pPr.numPr if style.element.pPr is not None else None
            if num_id is None and style_num is not None and style_num.numId is not None:
                num_id=style_num.numId.val
            if level is None and style_num is not None and style_num.ilvl is not None:
                level=style_num.ilvl.val
            style=style.base_style
        if num_id is None or num_id==0 or num_id not in self.definitions:return None
        levels=self.definitions[num_id]
        if level is None:
            level=next((i for i,definition in levels.items() if definition['style'] in styles and definition['style']),None)
        if level is None and fallback_level is not None:level=fallback_level-1
        if level not in levels:return None
        counters=self.counters.setdefault(num_id,{})
        counters[level]=counters.get(level,levels[level]['start']-1)+1
        for deeper in list(counters):
            if deeper>level:del counters[deeper]
        pattern=levels[level]['text']
        def substitute(match):
            index=int(match[1])-1
            if index not in counters or index not in levels:raise ValueError('编号父级缺失')
            value=counters[index]
            fmt=levels[index]['format']
            if fmt=='upperLetter':
                result=''
                while value:
                    value,remainder=divmod(value-1,26)
                    result=chr(65+remainder)+result
                return result
            if fmt=='decimal':return str(value)
            raise ValueError('编号格式不支持')
        try:return re.sub(r'%(\d+)',substitute,pattern) if pattern else None
        except ValueError:return None


def source_table(table, table_id, titles, caption, location):
    cells=[]; active_merges={}; headers=[]
    for row_number, row in enumerate(table._tbl.tr_lst,1):
        before=row.find('./'+qn('w:trPr')+'/'+qn('w:gridBefore'))
        col=int(before.get(qn('w:val'))) if before is not None else 0
        if row_number==1: headers=['']*col
        next_merges={}
        for tc in row.tc_lst:
            span=tc.find('./'+qn('w:tcPr')+'/'+qn('w:gridSpan'))
            width=int(span.get(qn('w:val'))) if span is not None else 1
            merge=tc.find('./'+qn('w:tcPr')+'/'+qn('w:vMerge'))
            v_merge=merge.get(qn('w:val'),'continue') if merge is not None else None
            value='\n'.join(Paragraph(p,table).text for p in tc.findall(qn('w:p')))
            origin=f'{table_id}r{row_number}c{col+1}'
            if v_merge=='continue': origin=active_merges.get(col,origin)
            for offset in range(width):
                logical_col=col+offset
                if v_merge is not None: next_merges[logical_col]=origin
                if row_number==1: headers.append(value)
                cells.append({'row':row_number,'col':logical_col+1,
                              'raw_label':headers[logical_col] if logical_col<len(headers) else '',
                              'raw_value':value,'grid_span':width,'v_merge':v_merge,
                              'source_cell':origin})
            col+=width
        active_merges=next_merges
    nested=bool(table._tbl.xpath('.//w:tc/w:tbl'))
    return {'table_id':table_id,'chapter_path':list(titles),'parent_titles':list(titles),
            'caption':caption,'headers':headers,'cells':cells,'location':location,
            'parse_status':'nested_table' if nested else ('parsed' if titles else 'unknown_section')}


def parse_docx(data, role, source_version=None):
    safe_zip(data,'word/document.xml')
    doc=WordDocument(BytesIO(data))
    document_sha256=hashlib.sha256(data).hexdigest()
    result={'document_sha256':document_sha256,'document_version':source_version,
            'blocks':[],'sections':[],'source_tables':[],
            'assets':[],'records':[],'risk_tables':[],'diagnostics':[],'facts':{},'tables':0}
    chapter='OTHER'; domain=''; extension='general'; object_name=''; recent=[]; ordinal=0
    headings=[]; numbered_headings=[]; numbering=NumberingResolver(doc)
    layer_orders={};object_orders={}
    section_stack=[]; body_paragraph=0

    def add_block(kind, text, location, region='body', section_id=None, **extra):
        block_id=f'b{len(result["blocks"])+1}'
        block={'id':block_id,'order':len(result['blocks'])+1,'type':kind,'region':region,
               'section_id':section_id,'text':text,'search_text':norm(text),
               'source':{'document_sha256':document_sha256,'document_role':role,
                         'document_version':source_version,'block_id':block_id,'location':location}}
        block.update(extra)
        result['blocks'].append(block)
        if region=='body' and kind!='toc':
            for section in section_stack:section['end_block']=block_id
        return block

    def open_section(title, level, number, number_source, block_id, paragraph):
        section_stack[:]=[section for section in section_stack if section['level']<level]
        section={'id':f's{len(result["sections"])+1}','parent_id':section_stack[-1]['id'] if section_stack else None,
                 'code':chapter,'title':title,'paragraph':paragraph,'level':level,
                 'number':number,'number_source':number_source,
                 'number_status':'resolved' if number else ('not_applicable' if chapter!='OTHER' else 'pending'),
                 'recognition_status':'identified' if chapter!='OTHER' else 'unclassified',
                 'order':len(result['sections'])+1,'start_block':block_id,'end_block':block_id}
        result['sections'].append(section);section_stack.append(section)
        return section

    def ensure_unclassified(block):
        if section_stack:return
        result['diagnostics'].append(f'{block["source"]["location"]}：未归类内容，需人工定位章节')
        section=open_section('未归类内容',1,None,'none',block['id'],0)
        block['section_id']=section['id']

    for element in body_elements(doc.element.body):
        if element.tag.endswith('}p'):
            p=Paragraph(element,doc); raw_text=p.text; text=raw_text.strip()
            body_paragraph+=1
            style=p.style.name if p.style else ''
            location=f'正文 · 段落{body_paragraph}'
            images,textboxes=content_references(element,location)
            if not text and not images and not textboxes:continue
            if 'toc' in style.lower() or '目录' in style:
                add_block('toc',raw_text,location,images=images,textboxes=textboxes)
                continue
            level=heading_level(p)
            explicit=explicit_number(text)
            normal_numbered=bool(re.match(r'^\s*(?:第\s*[1-8]\s*章|附录\s*[A-H])',text,re.I))
            if not normal_numbered and explicit and '.' in explicit and len(text)<100:
                normal_numbered=True
            if normal_numbered and level is None:
                level=explicit.count('.')+1 if explicit and '.' in explicit else 1
            label=None
            if level is not None:
                headings=[heading for heading in headings if heading[0]<level]
                headings.append((level,text))
                numbered_headings=[heading for heading in numbered_headings if heading[0]<level]
                label=numbering.label(p,level)
                if label:numbered_headings.append((level,label,ordinal+1))
            old=chapter; chapter=chapter_for((label+' '+text) if label else text,style,chapter,level is not None)
            if level==1 and chapter==old and not normal_numbered:
                chapter='OTHER'
                result['diagnostics'].append(f'{location}：{text} 未归类，需人工定位章节')
            is_section=chapter!=old or level is not None or '标题' in style or 'Heading' in style
            if is_section:
                section_level=level or 1
                number=label or explicit
                block_id=f'b{len(result["blocks"])+1}'
                section=open_section(text,section_level,number,'automatic' if label else ('explicit' if number else 'none'),block_id,ordinal)
            block=add_block('paragraph',raw_text,location,section_id=section_stack[-1]['id'] if section_stack else None,
                            images=images,textboxes=textboxes)
            if not is_section:ensure_unclassified(block)
            if images:result['diagnostics'].append(f'{location}：图片仅保留引用，未提取图片文字')
            if textboxes:result['diagnostics'].append(f'{location}：文本框未纳入正文文字，需人工核实')
            for name in DOMAINS:
                if norm(text).endswith(norm(name)) and len(text)<35:
                    domain=name; object_name=''; extension='general'; break
            for word,code in [('云计算','cloud'),('移动互联','mobile'),('物联网','iot'),('工业控制','ics'),('电力行标','power'),('大数据','bigdata'),('安全通用要求','general')]:
                if word in text and '要求' in text and len(text)<45:
                    extension=code; object_name=''; break
            if chapter=='APP_D' and ('四级标题' in style or '五级标题' in style or level is not None and level>=4 or re.match(r'D\.\d+\.\d+\.\d+',text)):
                object_name=text
            recent.append(text); recent=recent[-7:]; ordinal+=1
            continue
        if element.tag == qn('w:altChunk'):
            external_id=element.get(qn('r:id'),'')
            location=f'正文 · altChunk {external_id}'
            add_block('unsupported','',location,unsupported_tag='altChunk')
            result['diagnostics'].append(f'{location}：外部内容未解析，需人工核实')
            continue
        if not element.tag.endswith('}tbl'): continue
        table=Table(element,doc); result['tables']+=1; ti=result['tables']
        table_location=f'正文 · 表{ti}'
        images=[];textboxes=[]
        for row_number,xml_row in enumerate(element.tr_lst,1):
            for col_number,xml_cell in enumerate(xml_row.tc_lst,1):
                cell_images,cell_textboxes=content_references(xml_cell,f't{ti}r{row_number}c{col_number}')
                images.extend(cell_images);textboxes.extend(cell_textboxes)
        nested_tables=[]
        for index,nested in enumerate(element.xpath('.//w:tc/w:tbl'),1):
            cell=nested.getparent(); row=cell.getparent()
            row_number=row.getparent().tr_lst.index(row)+1
            col_number=row.tc_lst.index(cell)+1
            nested_tables.append({'location':f't{ti}r{row_number}c{col_number} · 嵌套表{index}'})
        block=add_block('table','',table_location,section_id=section_stack[-1]['id'] if section_stack else None,
                        table_id=f't{ti}',images=images,textboxes=textboxes,nested_tables=nested_tables)
        ensure_unclassified(block)
        if images:result['diagnostics'].append(f'{table_location}：图片仅保留引用，未提取图片文字')
        if textboxes:result['diagnostics'].append(f'{table_location}：文本框未纳入表格文字，需人工核实')
        rows=[[cell.text.strip() for cell in row.cells] for row in table.rows]
        caption=recent[-1] if recent else ''
        context=' / '.join(recent[-4:]); location=f'{chapter} · 表{ti}'
        source=source_table(table,f't{ti}',[title for _,title in headings],caption,location)
        source['block_id']=block['id'];source['document_sha256']=document_sha256
        source['document_version']=source_version
        result['source_tables'].append(source)
        if source['parse_status']=='nested_table':
            for index,nested in enumerate(element.xpath('.//w:tc/w:tbl'),1):
                nested_source=source_table(Table(nested,doc),f't{ti}n{index}',
                                           [title for _,title in headings],caption,
                                           f'{location} · 嵌套表{index}')
                nested_source.update({'block_id':block['id'],'parent_table_id':f't{ti}',
                                      'document_sha256':document_sha256,
                                      'document_version':source_version})
                result['source_tables'].append(nested_source)
            result['diagnostics'].append(f'{location}：外层含嵌套表，已索引内层，仍需核实复杂布局')
            continue
        if not rows: continue
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
                management=domain in DOMAINS[5:]
                object_status='identified' if object_name else ('layer_level' if management else 'pending')
                shown_object=object_name or ('层面级／无单独对象' if management else '对象待定位')
                layer_orders.setdefault(domain,len(layer_orders)+1)
                object_orders.setdefault((domain,shown_object),len([key for key in object_orders if key[0]==domain])+1)
                heading=numbered_headings[-1] if numbered_headings else None
                chapter_number=heading[1] if heading else '章节号待定位'
                root_heading=next((x[1] for x in numbered_headings if x[0]==1),None)
                if heading and root_heading and root_heading.startswith('附录'):
                    root_suffix=root_heading[2:]
                    if chapter_number.startswith(root_suffix) and not chapter_number.startswith('附录'):
                        chapter_number='附录'+chapter_number
                result['records'].append({'id':evidence_id,'chapter':'APP_D',
                                          'chapter_number':chapter_number,
                                          'chapter_status':'resolved' if heading else 'pending',
                                          'heading_source':f'段落{heading[2]}' if heading else '',
                                          'layer_order':layer_orders[domain],
                                          'object_order':object_orders[(domain,shown_object)],
                                          'source_order':len(result['records'])+1,
                                          'object_status':object_status,
                                          'domain':domain,'extension':extension,'object':shown_object,
                                          'control':vals['control'],'requirement':vals['requirement'],
                                          'text':vals['text'],'verdict':vals['verdict'],
                                          'source':f'附录D · 表{ti} · 第{ri}行','evidence_id':evidence_id})
            continue
        # Asset inventories have a name column and at least one business attribute.
        for hi,header in enumerate(rows[:5]):
            name_indices=[i for i,h in enumerate(header) if header_key(h) in [header_key(x) for x in NAME_HEADERS]]
            if not name_indices or len(set(header))<3: continue
            ni=name_indices[0]; kind=asset_type(header,caption)
            # Chapter context takes precedence over reused table numbers.
            plan_caption=re.search(r'表\s*([234])\s*[-－]',caption)
            if role=='plan' and (chapter not in ('CH02','CH03','OTHER') or (chapter=='OTHER' and (not plan_caption or plan_caption[1]=='4'))):
                break
            if role=='report' and chapter not in ('OTHER','APP_A'):
                break
            sample=(role=='plan' and (chapter=='CH03' or (chapter=='OTHER' and bool(plan_caption and plan_caption[1]=='3')))) or (role=='report' and chapter=='OTHER') or ('抽选' in caption or '抽样' in caption or '测评对象选择' in caption or '测评对象选取' in caption)
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
    seen_parts=set()
    for section_number,section in enumerate(doc.sections,1):
        containers=[('header',section.header),('footer',section.footer)]
        if section.different_first_page_header_footer:
            containers.extend([('header',section.first_page_header),('footer',section.first_page_footer)])
        if doc.settings.odd_and_even_pages_header_footer:
            containers.extend([('header',section.even_page_header),('footer',section.even_page_footer)])
        for region,container in containers:
            part_name=str(container.part.partname)
            if part_name in seen_parts:continue
            seen_parts.add(part_name)
            for paragraph_number,paragraph in enumerate(container.paragraphs,1):
                if paragraph.text.strip():
                    add_block('paragraph',paragraph.text,f'{region} · 第{section_number}节 · 段落{paragraph_number}',region=region)
    if role=='report' and not result['records']: result['diagnostics'].append('未识别到附录D结果记录；请检查表头和章节结构')
    if not result['assets']: result['diagnostics'].append('未识别到资产清单；不可据此认定不存在资产')
    result['counts']={'assets':len(result['assets']),'records':len(result['records']),'tables':result['tables']}
    return result

