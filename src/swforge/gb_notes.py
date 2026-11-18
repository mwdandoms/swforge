"""Explicit drawing notes and visible template title fields, verified natively.

No tolerance class, roughness, chamfer or heat treatment is chosen by default.
Projection text is a label only, never certified as a projection graphic.
"""
from __future__ import annotations
import math
from .native_bridge import run_native, target_document

PLACEHOLDER_VALUES = {'图样名称','图样代号','材料','比例','设计','设计者',''}


def build_tech_requirements(items=None, *, material=None, general=False, extra=None,general_tolerance_class=None):
    if general:
        raise ValueError('Supply explicit approved items; no automatic manufacturing defaults')
    if isinstance(items,str) or isinstance(extra,str):
        raise ValueError('items/extra must be lists of individual requirements')
    result = [str(x).strip() for x in (items or []) if str(x).strip()]
    if material:result.append('材料：'+str(material).strip())
    result.extend(str(x).strip() for x in (extra or []) if str(x).strip())
    if general_tolerance_class is not None:
        from .gb_standards import general_tolerance_note
        result.append(general_tolerance_note(general_tolerance_class))
    return result


def format_title_block_fields(*, name=None, code=None, material=None, scale=None,
                              designer=None, date=None, company=None, sheet_count=None, weight_kg=None,
                              checker=None,reviewer=None,approver=None,change_mark=None,change_document=None):
    return {k:str(v).strip() if v is not None and str(v).strip() else None for k,v in zip(
        ('图样名称','图样代号','材料','比例','设计','日期','单位名称','张数','重量','校对','审核','批准','更改标记','更改文件号'),
        (name,code,material,scale,designer,date,company,sheet_count,weight_kg,checker,reviewer,approver,change_mark,change_document))}


def missing_title_block_fields(fields):
    return [k for k in ('图样名称','图样代号','材料','比例') if fields.get(k) is None or str(fields[k]).strip() in PLACEHOLDER_VALUES]


_ENGINE = r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;using SolidWorks.Interop.swconst;
public class __CLASS__ {
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
static JavaScriptSerializer json=new JavaScriptSerializer();
static List<INote> Notes(IDrawingDoc dr){var notes=new List<INote>();for(IView v=(IView)dr.GetFirstView();v!=null;v=(IView)v.GetNextView())foreach(object o in (object[])v.GetAnnotations()??new object[0]){var n=((IAnnotation)o).GetSpecificAnnotation() as INote;if(n!=null)notes.Add(n);}return notes;}
public static string Run(string request){try{
 var cmd=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));
 var sw=SwforgeConnection.Connect();
 if(sw.GetProcessID()!=Convert.ToInt32(cmd["process_id"]))throw new Exception("Process changed");
 var md=(IModelDoc2)sw.ActiveDoc;
 if(md==null||md.GetType()!=3||!String.Equals(md.GetPathName(),(string)cmd["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active drawing changed");
 if(typeof(ISldWorks).Assembly.GetName().Version.Major!=Int32.Parse(sw.RevisionNumber().Split('.')[0]))throw new Exception("Interop mismatch");
 var dr=(IDrawingDoc)md;var mgr=md.Extension.CustomPropertyManager[""];
 if((string)cmd["mode"]=="title"){
  var fields=(Dictionary<string,object>)cmd["fields"];var values=new Dictionary<string,object>();var visible=new Dictionary<string,object>();var codes=new Dictionary<string,object>();var missing=new List<string>();
  foreach(var kv in fields){string value=Convert.ToString(kv.Value);codes[kv.Key]=mgr.Add3(kv.Key,30,value,2);string raw,resolved;bool was,linked;int got=mgr.Get6(kv.Key,false,out raw,out resolved,out was,out linked);values[kv.Key]=resolved==""?raw:resolved;if((string)values[kv.Key]!=value)throw new Exception("Property readback mismatch: "+kv.Key);}
  var notes=Notes(dr);
  foreach(var kv in fields){string value=Convert.ToString(kv.Value);var found=new List<INote>();
   foreach(var n in notes){string text=n.GetText(),link=n.PropertyLinkedText??"";
    // Static headings such as 比例/设计 are labels, not editable value cells.
    bool quoted=text.Trim()!=text.Trim().Trim('"','“','”');
    bool placeholder=quoted&&text.Trim().Trim('"','“','”')==kv.Key;
    bool linkedField=link.IndexOf("$PRP:\""+kv.Key+"\"",StringComparison.Ordinal)>=0||link.IndexOf("$PRPSHEET:\""+kv.Key+"\"",StringComparison.Ordinal)>=0;
    if(placeholder||linkedField){n.PropertyLinkedText="$PRP:\""+kv.Key+"\"";found.Add(n);}}
   // Existing explicit values count only in the template/title area, not model annotations.
   if(found.Count==0)foreach(var n in notes){var pos=(double[])((IAnnotation)n.GetAnnotation()).GetPosition();if(n.GetText().Trim()==value&&pos[0]>.2&&pos[1]<.09)found.Add(n);}
   md.EditRebuild3();var actual=new List<string>();foreach(var n in found)actual.Add(n.GetText());visible[kv.Key]=actual;
   if(found.Count==0||actual.Exists(t=>t!=value))missing.Add(kv.Key);
  }
  return json.Serialize(R("ok",missing.Count==0,"modified",true,"properties",values,"visible_readback",visible,"missing_visible_fields",missing,"property_write_codes",codes,"review_required",true));
 }
 dr.ActivateView("");md.ClearSelection2(true);
 string body=(string)cmd["text"];INote note=null;bool inserted=true;
 if((string)cmd["mode"]=="tech")foreach(var existing in Notes(dr))if(existing.TagName=="SWFORGE_TECH_REQUIREMENTS"){note=existing;inserted=false;break;}
 if(note==null)note=(INote)md.InsertNote(body);else note.SetText(body);
 if(note==null)throw new Exception("InsertNote failed");
 if((string)cmd["mode"]=="tech")note.TagName="SWFORGE_TECH_REQUIREMENTS";
 var a=(IAnnotation)note.GetAnnotation();double x=Convert.ToDouble(cmd["x"]),y=Convert.ToDouble(cmd["y"]),h=Convert.ToDouble(cmd["height"]);
 bool positioned=a.SetPosition2(x,y,0);var fmt=(ITextFormat)a.GetTextFormat(0);fmt.CharHeight=h;bool formatted=a.SetTextFormat(0,false,fmt);md.EditRebuild3();
 string noteReadback=note.GetText();double[] notePos=(double[])a.GetPosition(),ext=(double[])note.GetExtent();var sheet=(ISheet)dr.GetCurrentSheet();double w=0,hh=0;sheet.GetSize(ref w,ref hh);
 bool bounds=ext!=null&&ext.Length==6&&Math.Min(ext[0],ext[3])>=0&&Math.Min(ext[1],ext[4])>=0&&Math.Max(ext[0],ext[3])<=w&&Math.Max(ext[1],ext[4])<=hh;
 bool ok=positioned&&formatted&&noteReadback.Replace("\r\n","\n")==body.Replace("\r\n","\n")&&!a.IsDangling()&&Math.Abs(notePos[0]-x)<1e-7&&Math.Abs(notePos[1]-y)<1e-7&&bounds;
 if((string)cmd["mode"]=="tech")mgr.Add3("技术要求",30,body,2);
 return json.Serialize(R("ok",ok,"modified",true,"inserted",inserted,"text",noteReadback,"position_m",notePos,"extent_m",ext,"bounds_inside_sheet",bounds,"dangling",a.IsDangling(),"approximate",(string)cmd["mode"]=="projection","review_required",true));
}catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString(),"mutation_state","inspect before retry"));}}
}
'''


def _prepare(drawing_path):
    if drawing_path is None:
        from .annotations import _drawing
        from .session import _value
        _, md = _drawing(None)
        drawing_path = str(_value(md,'GetPathName'))
    return target_document(drawing_path,3)[2]


def _note(mode,drawing_path,text,x,y,height):
    try:
        if not text:raise ValueError('Explicit text/items are required')
        if not all(math.isfinite(float(v)) and float(v)>0 for v in (x,y,height)):raise ValueError('Positive finite sheet metres required')
        return run_native(dict(_prepare(drawing_path),mode=mode,text=text,x=x,y=y,height=height),engine=_ENGINE)
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}','modified':False}


def add_tech_requirements(drawing_path=None,items=None,*,material=None,general=False,x_m=.04,y_m=.055,char_height_m=.0035,general_tolerance_class=None):
    try:lines=build_tech_requirements(items,material=material,general=general,general_tolerance_class=general_tolerance_class)
    except ValueError as exc:return {'ok':False,'error':str(exc),'modified':False}
    return _note('tech',drawing_path,'\n'.join(lines),x_m,y_m,char_height_m)


def fill_title_block(drawing_path=None,**fields):
    try:
        prepared={k:v for k,v in format_title_block_fields(**fields).items() if v is not None}
        if not prepared or any(v in PLACEHOLDER_VALUES for v in prepared.values()):raise ValueError('Explicit non-placeholder title fields required')
        return run_native(dict(_prepare(drawing_path),mode='title',fields=prepared),engine=_ENGINE)
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}','modified':False}


def add_projection_symbol(drawing_path=None,*,first_angle=True,x_m=.32,y_m=.27):
    from .gb_styles import set_projection
    if drawing_path is None:drawing_path=_prepare(None)['path']
    return set_projection(drawing_path,first_angle)
