"""Copy-only part variants: explicit dimensions, native readback and source protection."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

from .native_bridge import target_document,run_native
from .session import _value


def file_sha256(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def list_model_parameters(part_path):
    try:
        _,_,target=target_document(part_path,1)
        return run_native(dict(target,mode='parameters'))
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def _parameters(parameters):
    if not isinstance(parameters,dict) or len(parameters)>100:
        raise ValueError('parameters must be an object with at most 100 exact dimension keys')
    result={}
    for name,value in parameters.items():
        if not isinstance(name,str) or '@' not in name or not name.strip():
            raise ValueError('Use an exact key returned by list_model_parameters')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Parameter values must be finite positive millimetres')
        result[name]=float(value)
    return result


def create_variant(source_path,out_path,parameters=None,*,material=None,configuration=None,
                   drawing_path=None,summary_csv=None,keep_open=False):
    """Create a new part, optionally a fresh dimensioned drawing and single-part CSV.

    Never edits the source part. Exact linear dimension keys and existing configurations
    only. CSV is a single-part property summary, not an assembly BOM. No automatic
    tolerance/roughness decision is made. Any drawing failure is reported as partial.
    """
    source=Path(source_path).resolve();output=Path(out_path).resolve()
    owned=False;owned_drawing=False;model_verified=False;source_owned=False;sw=None;md=None
    result={'ok':False,'source':str(source),'output':str(output),'source_unchanged':False}
    try:
        parameters=_parameters({} if parameters is None else parameters)
        if not parameters and material is None and configuration is None:
            raise ValueError('Specify dimensions, material or an existing configuration')
        if source.suffix.lower()!='.sldprt' or output.suffix.lower()!='.sldprt' or not source.is_file():
            raise ValueError('Source/output must be .SLDPRT and source must exist')
        if output.exists() or source==output or source.name.casefold()==output.name.casefold():
            raise ValueError('Use a new output filename; source, existing files and colliding titles are protected')
        for path,suffix in ((drawing_path,'.slddrw'),(summary_csv,'.csv')):
            if path and (Path(path).suffix.lower()!=suffix or Path(path).exists()):
                raise ValueError('Output must have expected suffix and must not already exist')
        if material is not None:
            from .gb_materials import lookup,ensure_library
            if not isinstance(material,str) or lookup(material) is None:
                raise ValueError('Variant material must be an explicit supported GB material name')
            database=ensure_library()
        else:
            database=''
        if configuration is not None and (not isinstance(configuration,str) or not configuration):
            raise ValueError('configuration must be a nonempty existing configuration name')
        from .session import get_session
        from .resources import ensure_capacity
        sw=get_session().sw()
        original=sw.GetOpenDocumentByName(str(source))
        if original is not None and bool(_value(original,'GetSaveFlag')):
            raise ValueError('Source part has unsaved changes; save it explicitly before making a disk-based variant')
        before=file_sha256(source)
        needed=(1 if original is None else 0)+1+(1 if drawing_path else 0)
        if not ensure_capacity(needed)['allowed']:
            raise RuntimeError('Document capacity exceeded')
        output.parent.mkdir(parents=True,exist_ok=True)
        source_owned=original is None
        _,_,copy_target=target_document(source,1)
        copied=run_native(dict(copy_target,mode='copy',out=str(output)))
        result['copy']=copied
        if not copied.get('ok'):
            result.update(ok=False,error=copied.get('error','Native copy failed'),source_unchanged=file_sha256(source)==before)
            if copied.get('mutation_state')=='unknown':result['mutation_state']='unknown'
            return result
        owned=True
        _,md,target=target_document(output,1)
        from .gb_materials import lookup
        expected=lookup(material or copied.get('material',''))
        native=run_native(dict(target,mode='edit',parameters=parameters,material=material or '',
            material_db=database,configuration=configuration or '',density_kg_m3=expected[0] if expected else copied['density_kg_m3']))
        result.update(native)
        result['source_unchanged']=file_sha256(source)==before
        if not result['source_unchanged']:
            result['ok']=False;result['error']='Source fingerprint changed during operation'
        if not result.get('ok'):
            if result.get('mutation_state')!='unknown':
                sw.CloseDoc(_value(md,'GetTitle'));md=None
                output.unlink();owned=False
                result['rollback_ok']=not output.exists() and result['source_unchanged']
            return result
        model_verified=True
        if drawing_path:
            from .drawing import produce,add_dimensions,_save_as
            drawing=produce(str(output),str(Path(drawing_path).resolve()),keep_open=True)
            result['drawing']=drawing
            if not drawing.get('ok'):
                result.update(ok=False,partial_outputs=[str(output)])
                return result
            owned_drawing=True
            dims=add_dimensions(drawing['drawing'],overall=True)
            result['drawing_dimensions']=dims
            if not dims.get('ok') or not _save_as(sw.ActiveDoc,drawing['drawing'])[0]:
                result.update(ok=False,error='Variant drawing dimensions/save failed',partial_outputs=[str(output),drawing['drawing']])
                return result
            from .drawing_review import record_drawing_revision
            stamp=record_drawing_revision(drawing['drawing'])
            result['drawing_revision']=stamp
            if not stamp.get('ok'):
                result.update(ok=False,error='Variant drawing revision could not be verified')
                return result
        if summary_csv:
            path=Path(summary_csv);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=['part','configuration','quantity','material','mass_kg','volume_mm3'])
                writer.writeheader();writer.writerow(dict(part=output.name,configuration=result['configuration'],quantity=1,
                    material=result['material'],mass_kg=result['mass_kg'],volume_mm3=result['volume_mm3']))
            result['summary_csv']=str(path.resolve())
        result.update(review_required=True,ready_for_manufacture=False)
        return result
    except Exception as exc:
        result.update(ok=False,error=f'{type(exc).__name__}: {exc}')
        if owned and md is not None and not model_verified:
            try:
                sw.CloseDoc(_value(md,'GetTitle'));md=None
                output.unlink();result['rollback_ok']=not output.exists()
            except Exception as rollback:
                result['rollback_ok']=False;result['rollback_error']=str(rollback)
        elif model_verified:
            result['partial_outputs']=[str(output)]+([str(Path(drawing_path).resolve())] if owned_drawing else [])
        return result
    finally:
        if not keep_open and sw is not None:
            # Only close exact documents created by this call; never close source.
            for path in (drawing_path if owned_drawing else None,str(output) if owned else None):
                if not path:continue
                try:
                    document=sw.GetOpenDocumentByName(str(Path(path).resolve()))
                    if document is not None:sw.CloseDoc(_value(document,'GetTitle'))
                except Exception:pass
        if source_owned and sw is not None:
            try:
                source_doc=sw.GetOpenDocumentByName(str(source))
                if source_doc is not None and not bool(_value(source_doc,'GetSaveFlag')):
                    sw.CloseDoc(_value(source_doc,'GetTitle'))
            except Exception:pass
