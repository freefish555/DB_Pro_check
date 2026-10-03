import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from backend.documents import parse_docx


def _numbering(document, inherited):
    root = document.part.numbering_part.element
    abstract_ids = [int(x.get(qn('w:abstractNumId'))) for x in root.findall(qn('w:abstractNum'))]
    num_ids = [int(x.get(qn('w:numId'))) for x in root.findall(qn('w:num'))]
    abstract_id, num_id = max(abstract_ids, default=0) + 1, max(num_ids, default=0) + 1
    abstract = OxmlElement('w:abstractNum')
    abstract.set(qn('w:abstractNumId'), str(abstract_id))
    for level, fmt, label in ((0, 'upperLetter', '附录%1'), (1, 'decimal', '%1.%2'),
                              (2, 'decimal', '%1.%2.%3'), (3, 'decimal', '%1.%2.%3.%4')):
        lvl = OxmlElement('w:lvl'); lvl.set(qn('w:ilvl'), str(level))
        for tag, value in (('start', '1'), ('numFmt', fmt), ('lvlText', label)):
            child = OxmlElement(f'w:{tag}'); child.set(qn('w:val'), value); lvl.append(child)
        if inherited:
            child = OxmlElement('w:pStyle')
            child.set(qn('w:val'), document.styles[f'Heading {level+1}'].style_id)
            lvl.append(child)
        abstract.append(lvl)
    root.append(abstract)
    num = OxmlElement('w:num'); num.set(qn('w:numId'), str(num_id))
    reference = OxmlElement('w:abstractNumId'); reference.set(qn('w:val'), str(abstract_id))
    num.append(reference); root.append(num)
    return num_id


def _set_num(target, num_id, level=None):
    properties = target._p.get_or_add_pPr() if hasattr(target, '_p') else target.element.get_or_add_pPr()
    num = OxmlElement('w:numPr')
    if level is not None:
        ilvl = OxmlElement('w:ilvl'); ilvl.set(qn('w:val'), str(level)); num.append(ilvl)
    id_element = OxmlElement('w:numId'); id_element.set(qn('w:val'), str(num_id)); num.append(id_element)
    properties.append(num)


def _record(document):
    table = document.add_table(rows=1, cols=4)
    for cell, text in zip(table.rows[0].cells, ('控制点', '测评项', '结果记录', '符合情况')):
        cell.text = text
    for cell, text in zip(table.add_row().cells, ('身份鉴别', '应鉴别用户', '已检查身份鉴别配置', '符合')):
        cell.text = text


def _document(inherited=False, numbered=True, management=False):
    document = Document()
    num_id = _numbering(document, inherited) if numbered else None
    if inherited:
        for level in (1, 2, 3, 4):
            _set_num(document.styles[f'Heading {level}'], num_id)
    for title in ('资产清单', '工具列表', '其他材料', '单项测评结果记录'):
        heading = document.add_paragraph(title, style='Heading 1')
        if numbered and not inherited:_set_num(heading, num_id, 0)
    layer = document.add_paragraph('安全管理制度' if management else '安全通信网络', style='Heading 2')
    if numbered and not inherited:_set_num(layer, num_id, 1)
    if not management:
        control = document.add_paragraph('身份鉴别', style='Heading 3')
        if numbered and not inherited:_set_num(control, num_id, 2)
        obj = document.add_paragraph('测评对象 A', style='Heading 4')
        if numbered and not inherited:_set_num(obj, num_id, 3)
    _record(document)
    data = io.BytesIO(); document.save(data)
    return data.getvalue()


def test_direct_numbering_resolves_appendix_heading():
    record = parse_docx(_document(), 'report')['records'][0]
    assert record['chapter_number'].startswith('附录D')
    assert record['chapter_status'] == 'resolved'
    assert record['heading_source']
    assert record['object_status'] == 'identified'


def test_style_inherited_numbering_resolves_parent_title():
    record = parse_docx(_document(inherited=True), 'report')['records'][0]
    assert record['chapter_number'].startswith('附录D')
    assert record['chapter_status'] == 'resolved'


def test_unresolved_numbering_is_pending():
    record = parse_docx(_document(numbered=False), 'report')['records'][0]
    assert record['chapter_number'] == '章节号待定位'
    assert record['chapter_status'] == 'pending'


def test_layer_record_without_object_differs_from_missing_heading():
    layer = parse_docx(_document(management=True), 'report')['records'][0]
    missing = parse_docx(_document(), 'report')['records'][0]
    assert layer['object_status'] == 'layer_level'
    assert layer['object'] == '层面级／无单独对象'
    assert missing['object_status'] == 'identified'
    assert layer['layer_order'] == 1 and layer['source_order'] == 1
