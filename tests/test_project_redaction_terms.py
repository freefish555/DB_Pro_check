import os
import tempfile

os.environ.setdefault('REVIEW_DATA_DIR', tempfile.mkdtemp(prefix='redaction-terms-'))

from backend.app import project_redaction_terms
from backend.redaction import prepare_model_request


def test_extracted_contact_and_address_redact_unlabeled_result_prose():
    table = {'table_id': 't1', 'block_id': 'b1', 'caption': '报告基本信息表',
             'chapter_path': ['基本信息表'], 'parse_status': 'parsed',
             'cells': [
                 {'row': 1, 'col': 1, 'raw_value': '被测单位'},
                 {'row': 1, 'col': 2, 'raw_value': ''},
                 {'row': 2, 'col': 1, 'raw_value': '联系人'},
                 {'row': 2, 'col': 2, 'raw_value': '王测试'},
                 {'row': 3, 'col': 1, 'raw_value': '单位地址'},
                 {'row': 3, 'col': 2, 'raw_value': '测试市测试路八号'},
             ]}
    document = type('Doc', (), {'id': 'd1', 'version': 1, 'sha256': 'x',
                                'parsed': {'source_tables': [table]}})()
    for cell in table['cells']:
        cell['source_cell'] = f"t1r{cell['row']}c{cell['col']}"
    terms = project_redaction_terms({}, {'report': document})
    prepared = prepare_model_request(
        {'text': '王测试在测试市测试路八号核查设备。'}, terms, {},
        {'prompt_version': 'v1', 'knowledge_version': 'v1', 'service_url': 'http://localhost',
         'model_config_version': 'v1'})
    assert '王测试' not in prepared.payload['text']
    assert '测试市测试路八号' not in prepared.payload['text']
