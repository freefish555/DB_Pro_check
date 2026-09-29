"""Local operator commands; never place the supplied business workbooks in Git."""
import hashlib
import sys
from pathlib import Path

from sqlalchemy import select

from .catalog import import_workbook
from .db import Base, engine, Session, Knowledge


def import_catalog(folder):
    Base.metadata.create_all(engine)
    source=Path(folder)
    paths=[source] if source.is_file() and source.suffix.lower()=='.xlsx' else list(source.glob('*.xlsx'))
    if not paths:raise SystemExit('目录中没有 XLSX 文件')
    with Session() as db:
        for path in paths:
            raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            if db.scalar(select(Knowledge.id).where(Knowledge.sha256==sha)):
                print(path.name,'already imported');continue
            content=import_workbook(raw,path.name)
            row=Knowledge(filename=path.name,sha256=sha,family=content['family'],level=content['level'],profile=content['profile'],content=content,status='published')
            db.add(row)
            print(path.name,len(content.get('requirements',[])),'条',len(content.get('warnings',[])),'条提示')
        db.commit()


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='import-catalog':raise SystemExit('用法：python -m backend.cli import-catalog <Excel目录>')
    import_catalog(sys.argv[2])

