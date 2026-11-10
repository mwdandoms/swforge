"""Dependency-isolated assembly variants and configuration-aware BOM inspection."""
from __future__ import annotations
from pathlib import Path
import json,os,math
from .native_bridge import target_document,run_native
from .variants import file_sha256,_parameters
from .session import _value,get_session

_ENGINE=r'''
using System;using System.IO;using System.Collections;using System.Collections.Generic;using System.Runtime.InteropServices;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static ISldWorks sw;static IModelDoc2 md;static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16777216};static Dictionary<string,IComponent2> objects=new Dictionary<string,IComponent2>();
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
static string S(Dictionary<string,object> c,string k){return c.ContainsKey(k)?Convert.ToString(c[k]):"";}
static List<object> components=new List<object>();static List<object> mates=new List<object>();
static void Mates(IModelDoc2 doc,string scope){for(IFeature f=(IFeature)doc.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())if(f.GetTypeName2()=="MateGroup")for(IFeature m=(IFeature)f.GetFirstSubFeature();m!=null;m=(IFeature)m.GetNextSubFeature()){var mate=m.GetSpecificFeature2() as IMate2;if(mate!=null){bool warning=false;int err=m.GetErrorCode2(out warning);mates.Add(R("scope",scope,"name",m.Name,"type",mate.Type,"error",err,"warning",warning));}}}
static void Children(IComponent2 parent,string parentKey,bool parentSuppressed,bool parentExcluded){
 foreach(object o in (object[])parent.GetChildren()??new object[0]){var c=(IComponent2)o;string key=parentKey+"/"+c.GetID();objects[key]=c;
 bool suppressed=parentSuppressed||c.GetSuppression()==0,excluded=parentExcluded||c.ExcludeFromBOM;var doc=(IModelDoc2)c.GetModelDoc2();string path=c.GetPathName();string material="",db="";object configs=null;
 if(doc!=null){configs=doc.GetConfigurationNames();if(doc.GetType()==1){material=((IPartDoc)doc).GetMaterialPropertyName2(c.ReferencedConfiguration,out db);if(material=="")material=((IPartDoc)doc).GetMaterialPropertyName2("",out db);}}
 var row=R("instance_key",key,"name",c.Name2,"path",path,"configuration",c.ReferencedConfiguration,"configurations",configs,"suppressed",suppressed,"exclude_from_bom",excluded,"own_exclude_from_bom",c.ExcludeFromBOM,"resolved",doc!=null,"virtual",c.IsVirtual,"is_assembly",path.EndsWith(".sldasm",StringComparison.OrdinalIgnoreCase),"material",material,"transform",c.Transform2!=null?c.Transform2.ArrayData:null);
 components.Add(row);if(doc!=null&&doc.GetType()==2){Mates(doc,key);Children(c,key,suppressed,excluded);}
 }
}
static object Snapshot(){components.Clear();mates.Clear();objects.Clear();var root=(IComponent2)md.ConfigurationManager.ActiveConfiguration.GetRootComponent3(true);Children(root,"",false,false);Mates(md,"");
 var pack=(IPackAndGo)md.Extension.GetPackAndGo();pack.IncludeSuppressed=true;pack.IncludeDrawings=false;object docs;pack.GetDocumentNames(out docs);
 return R("ok",true,"path",md.GetPathName(),"modified",md.GetSaveFlag(),"configuration",md.ConfigurationManager.ActiveConfiguration.Name,"components",components,"mates",mates,"dependencies",docs);
}
public static string Run(string request){try{var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));md=(IModelDoc2)sw.ActiveDoc;
if(sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||md==null||md.GetType()!=2||!String.Equals(md.GetPathName(),S(c,"path"),StringComparison.OrdinalIgnoreCase))throw new Exception("Active assembly changed");
if(typeof(ISldWorks).Assembly.GetName().Version.Major!=Int32.Parse(sw.RevisionNumber().Split('.')[0]))throw new Exception("Interop mismatch");
string mode=S(c,"mode");if(mode=="snapshot")return json.Serialize(Snapshot());
if(mode=="pack"){
var pack=(IPackAndGo)md.Extension.GetPackAndGo();pack.IncludeSuppressed=true;pack.IncludeDrawings=false;pack.IncludeToolboxComponents=true;pack.FlattenToSingleFolder=true;object docs;pack.GetDocumentNames(out docs);var names=(string[])docs;var mapping=(Dictionary<string,object>)c["mapping"];var destinations=new BStrWrapper[names.Length];
for(int i=0;i<names.Length;i++){if(!mapping.ContainsKey(names[i]))throw new Exception("Dependencies changed before copy");string dest=Convert.ToString(mapping[names[i]]);if(File.Exists(dest))throw new Exception("Output exists");destinations[i]=new BStrWrapper(dest);var open=(IModelDoc2)sw.GetOpenDocumentByName(names[i]);if(open!=null&&open.GetSaveFlag())throw new Exception("Dependency has unsaved changes");}
if(!pack.SetDocumentSaveToNames(destinations))throw new Exception("Pack and Go path mapping rejected");var statuses=(int[])md.Extension.SavePackAndGo((PackAndGo)pack);foreach(int status in statuses)if(status!=0)throw new Exception("Pack and Go save status "+status);
return json.Serialize(R("ok",true,"statuses",statuses,"mapping",mapping));
}
if(mode=="edit"){
Snapshot();foreach(Dictionary<string,object> change in (ArrayList)c["changes"]){string key=S(change,"instance_key");if(!objects.ContainsKey(key))throw new Exception("Occurrence changed: "+key);var comp=objects[key];
if(change.ContainsKey("configuration")){comp.ReferencedConfiguration=S(change,"configuration");if(comp.ReferencedConfiguration!=S(change,"configuration"))throw new Exception("Configuration rejected");}
if(change.ContainsKey("exclude_from_bom")){comp.ExcludeFromBOM=Convert.ToBoolean(change["exclude_from_bom"]);if(comp.ExcludeFromBOM!=Convert.ToBoolean(change["exclude_from_bom"]))throw new Exception("BOM exclusion rejected");}
if(change.ContainsKey("suppressed")){bool suppressed=Convert.ToBoolean(change["suppressed"]);int code=comp.SetSuppression2(suppressed?0:2);if((comp.GetSuppression()==0)!=suppressed)throw new Exception("Suppression rejected code="+code);}}
md.ForceRebuild3(false);int errors=0,warnings=0;if(!md.Save3(1,ref errors,ref warnings)||errors!=0)throw new Exception("Assembly save failed");return json.Serialize(Snapshot());
}
throw new Exception("Unknown mode");
}catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString()));}}
}
'''


def inspect_assembly(assembly_path):
    from .resources import document_inventory
    sw=get_session().sw();initial={str(Path(r['path']).resolve()).casefold() for r in document_inventory(sw)['documents'] if r['path']}
    result={}
    try:
        _,_,guard=target_document(assembly_path,2)
        result=run_native(dict(guard,mode='snapshot'),engine=_ENGINE)
        return result
    finally:
        for p in result.get('dependencies',[str(assembly_path)]):
            if str(Path(p).resolve()).casefold() not in initial:sw.CloseDoc(p)


def assembly_bom(snapshot,*,mode='parts_only'):
    if not snapshot.get('ok'):raise ValueError('Valid native assembly snapshot required')
    if mode not in ('parts_only','top_level'):raise ValueError('mode is parts_only/top_level')
    groups={};pending=[]
    for c in snapshot['components']:
        if c['suppressed'] or c['exclude_from_bom']:continue
        if mode=='top_level' and c['instance_key'].count('/')!=1:continue
        if mode=='parts_only' and c['is_assembly']:continue
        if not c['resolved']:pending.append(c['instance_key']);continue
        key=(os.path.normcase(os.path.abspath(c['path'])),c['configuration'],c['material'])
        row=groups.setdefault(key,dict(path=c['path'],configuration=c['configuration'],material=c['material'],quantity=0,instances=[]))
        row['quantity']+=1;row['instances'].append(c['instance_key'])
    return dict(ok=not pending,mode=mode,rows=list(groups.values()),unresolved=pending,
                total_quantity=sum(x['quantity'] for x in groups.values()),review_required=True)


def plan_assembly_variant(source_path,out_directory,*,changes=None,part_changes=None):
    try:
        source=Path(source_path).resolve();out=Path(out_directory).resolve()
        if out.exists():raise ValueError('Use an entirely new output directory')
        snap=inspect_assembly(source)
        if not snap.get('ok'):raise ValueError(str(snap))
        if snap['modified']:raise ValueError('Save source assembly explicitly before preview')
        if any(c['virtual'] for c in snap['components']):raise ValueError('Virtual components must first be saved externally')
        if any(not c['resolved'] and not c['suppressed'] for c in snap['components']):raise ValueError('Resolve active components before preview')
        rows={c['instance_key']:c for c in snap['components']};changes=changes or [];part_changes=part_changes or {}
        seen=set()
        for change in changes:
            if not isinstance(change,dict) or set(change)-{'instance_key','configuration','suppressed','exclude_from_bom'}:raise ValueError('Unknown occurrence change fields')
            key=change.get('instance_key')
            if key not in rows or key in seen:raise ValueError('Missing/duplicate occurrence target')
            seen.add(key)
            for field in ('suppressed','exclude_from_bom'):
                if field in change and not isinstance(change[field],bool):raise ValueError(field+' must be boolean')
            if 'configuration' in change and change['configuration'] not in (rows[key]['configurations'] or []):raise ValueError('Unknown occurrence configuration')
        dependencies=[str(Path(p).resolve()) for p in snap['dependencies']]
        if len(dependencies)>7:raise ValueError('This guarded workflow supports at most 7 dependency documents')
        mapping={p:str(out/(f'variant_{i:02d}_'+Path(p).name)) for i,p in enumerate(dependencies)}
        from .gb_materials import lookup
        normalized={}
        for p,edit in part_changes.items():
            p=str(Path(p).resolve())
            if p not in mapping or Path(p).suffix.lower()!='.sldprt' or set(edit)-{'parameters','material'}:raise ValueError('Exact copied part required')
            normalized[p]=dict(parameters=_parameters(edit.get('parameters',{})),material=edit.get('material'))
            if edit.get('material') and lookup(edit['material']) is None:raise ValueError('Unsupported material')
        return dict(ok=True,dry_run=True,source=str(source),output_directory=str(out),snapshot=snap,changes=changes,
                    part_changes=normalized,mapping=mapping,fingerprints={p:file_sha256(p) for p in dependencies},review_required=True)
    except Exception as exc:return {'ok':False,'dry_run':True,'error':f'{type(exc).__name__}: {exc}'}


def create_assembly_variant(plan):
    if not isinstance(plan,dict) or not plan.get('ok') or not plan.get('dry_run'):
        return {'ok':False,'error':'A successful fresh preview is required','rollback_ok':True}
    owned=[];out=None;unknown=False;sw=get_session().sw()
    from .resources import document_inventory,ensure_capacity
    initial={str(Path(d['path']).resolve()).casefold() for d in document_inventory(sw)['documents'] if d['path']}
    try:
        if not plan.get('ok') or not plan.get('dry_run'):raise ValueError('A successful fresh preview is required')
        fresh=plan_assembly_variant(plan['source'],plan['output_directory'],changes=plan['changes'],part_changes=plan['part_changes'])
        def signature(snap):
            rows=[]
            for c in snap['components']:
                row={k:c[k] for k in ('instance_key','path','configuration','suppressed','exclude_from_bom','virtual','resolved')}
                row['transform']=[round(x,9) for x in c['transform']] if c['transform'] else None
                rows.append(row)
            return dict(configuration=snap['configuration'],components=sorted(rows,key=lambda r:r['instance_key']),
                        mates=sorted(snap['mates'],key=lambda r:(r['scope'],r['name'])))
        if not fresh.get('ok') or any(fresh[k]!=plan[k] for k in ('mapping','fingerprints')) or signature(fresh['snapshot'])!=signature(plan['snapshot']):
            raise ValueError('Assembly/dependencies changed; preview again: '+str(fresh.get('error','snapshot identity')))
        if not ensure_capacity(len(plan['mapping']))['allowed']:raise ValueError('Not enough protected document capacity')
        out=Path(plan['output_directory']).resolve();out.mkdir(parents=True)
        _,_,guard=target_document(plan['source'],2)
        owned=list(plan['mapping'].values())
        packed=run_native(dict(guard,mode='pack',mapping=plan['mapping']),engine=_ENGINE,timeout_s=180)
        if packed.get('mutation_state')=='unknown':
            unknown=True
            return dict(ok=False,error='Copy timed out; inspect native state before retry',mutation_state='unknown',rollback_ok=False,partial_outputs=owned)
        if not packed.get('ok'):raise RuntimeError('Pack and Go failed: '+str(packed))
        for path in plan['mapping']:
            if str(Path(path).resolve()).casefold() not in initial:sw.CloseDoc(path)
        for source,edit in plan['part_changes'].items():
            clone=plan['mapping'][source];_,_,guard=target_document(clone,1)
            from .gb_materials import lookup,ensure_library
            material=edit.get('material') or ''
            # Existing native editor requires expected density; read copied source material.
            from .bom import material_of
            current=sw.ActiveDoc;mat=material or material_of(current);density=lookup(mat)
            if density is None:raise ValueError('Known material/density required for copied-part edits')
            result=run_native(dict(guard,mode='edit',parameters=edit['parameters'],configuration='',material=material,
                                   material_db=ensure_library() if material else '',density_kg_m3=density[0]))
            if result.get('mutation_state')=='unknown':
                unknown=True
                return dict(ok=False,error='Part edit timed out; inspect native state before retry',mutation_state='unknown',rollback_ok=False,partial_outputs=owned)
            if not result.get('ok'):raise RuntimeError('Copied part edit failed: '+str(result))
        root=plan['mapping'][plan['source']];_,_,guard=target_document(root,2)
        result=run_native(dict(guard,mode='edit',changes=plan['changes']),engine=_ENGINE)
        if result.get('mutation_state')=='unknown':
            unknown=True
            return dict(ok=False,error='Assembly edit timed out; inspect native state before retry',mutation_state='unknown',rollback_ok=False,partial_outputs=owned)
        if not result.get('ok'):raise RuntimeError(str(result))
        if any(not str(Path(c['path']).resolve()).casefold().startswith(str(out).casefold()+os.sep) for c in result['components'] if c['path']):raise RuntimeError('Copied assembly still references outside output directory')
        if any(m['error'] for m in result['mates']):raise RuntimeError('Copied assembly mate error')
        if len(result['mates'])!=len(plan['snapshot']['mates']):raise RuntimeError('Mate count changed during dependency copy')
        if any(file_sha256(p)!=sha for p,sha in plan['fingerprints'].items()):raise RuntimeError('Source dependency changed')
        report=dict(ok=True,assembly=root,source_unchanged=True,mapping=plan['mapping'],snapshot=result,bom=assembly_bom(result),review_required=True)
        (out/'variant_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report
    except Exception as exc:
        # Delete only explicitly owned files, never a recursive tree or source path.
        rollback=True
        for path in owned:
            try:
                p=Path(path).resolve()
                if out is None or p.parent!=out:raise ValueError('Rollback path outside owned directory')
                sw.CloseDoc(path)
                p.unlink(missing_ok=True)
            except Exception:rollback=False
        return dict(ok=False,error=f'{type(exc).__name__}: {exc}',rollback_ok=rollback,source_unchanged=all(file_sha256(p)==s for p,s in plan.get('fingerprints',{}).items()))
    finally:
        paths=set() if unknown else set(owned)|set(plan.get('mapping',{}))
        for path in paths:
            if str(Path(path).resolve()).casefold() not in initial:sw.CloseDoc(path)
