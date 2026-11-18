"""Native configuration-aware assembly BOM table insertion and component readback."""
from .native_bridge import target_document,run_native

_ENGINE=r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;using SolidWorks.Interop.sldworks;
public class __CLASS__{
static Dictionary<string,object> R(params object[] p){var r=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)r[(string)p[i]]=p[i+1];return r;}
public static string Run(string req){var json=new JavaScriptSerializer();try{var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(req));var sw=SwforgeConnection.Connect();var md=(IModelDoc2)sw.ActiveDoc;
if(md==null||md.GetType()!=3||sw.GetProcessID()!=Convert.ToInt32(c["process_id"])||!String.Equals(md.GetPathName(),(string)c["path"],StringComparison.OrdinalIgnoreCase))throw new Exception("Active drawing changed");var dr=(IDrawingDoc)md;var view=(IView)((IView)dr.GetFirstView()).GetNextView();if(view==null||!view.GetReferencedModelName().EndsWith(".sldasm",StringComparison.OrdinalIgnoreCase))throw new Exception("First view must reference an assembly");
dr.ActivateView("");md.ClearSelection2(true);view=(IView)((IView)dr.GetFirstView()).GetNextView();var bom=(IBomTableAnnotation)view.InsertBomTable4(false,.27,.13,1,(string)c["bom_mode"]=="parts_only"?1:2,view.ReferencedConfiguration,(string)c["template"],false,1,false);if(bom==null)throw new Exception("Native BOM creation failed; config="+view.ReferencedConfiguration+"; template="+c["template"]+"; model="+view.GetReferencedModelName());var table=(ITableAnnotation)bom;table.Anchored=false;table.AnchorType=1;table.GetAnnotation().SetPosition2(.27,.13,0);
// Preserve native item/part/quantity columns; explicit GB-oriented six-column profile.
if(table.ColumnCount!=4)throw new Exception("Expected four-column native template; provide a supported template");
table.SetColumnTitle2(0,"序号",false);table.SetColumnTitle2(1,"代号",false);table.SetColumnTitle2(2,"名称",false);table.SetColumnTitle2(3,"数量",false);
if(!table.InsertColumn2(4,0,"材料",0)||!table.InsertColumn2(4,0,"备注",0))throw new Exception("GB BOM column creation failed");
bom.SetColumnCustomProperty(4,"材料");
if(!table.SetHeader(2,1))throw new Exception("Bottom header rejected");
var format=(TextFormat)table.GetTextFormat();format.TypeFaceName="仿宋";format.CharHeight=.0035;table.SetTextFormat(false,format);
var rows=new List<object>();for(int i=0;i<table.RowCount;i++){var cells=new List<string>();for(int j=0;j<table.ColumnCount;j++)cells.Add(table.get_DisplayedText2(i,j,false));var components=new List<object>();foreach(object o in (object[])bom.GetComponents2(i,view.ReferencedConfiguration)??new object[0]){var comp=(IComponent2)o;components.Add(R("path",comp.GetPathName(),"configuration",comp.ReferencedConfiguration,"name",comp.Name2));}rows.Add(R("cells",cells,"components",components));}
md.EditRebuild3();return json.Serialize(R("ok",true,"type",table.Type,"rows",rows,"bom_mode",c["bom_mode"],"configuration",view.ReferencedConfiguration,"header_position",table.GetHeaderStyle(),"column_titles",new string[]{table.GetColumnTitle2(0,false),table.GetColumnTitle2(1,false),table.GetColumnTitle2(2,false),table.GetColumnTitle2(3,false),table.GetColumnTitle2(4,false),table.GetColumnTitle2(5,false)},"profile","GB-oriented six-column bottom header; missing part properties require engineering completion"));
}catch(Exception e){return json.Serialize(R("ok",false,"error",e.ToString()));}}}
'''

def insert_assembly_bom(drawing_path,*,mode='parts_only',template=None):
    if mode not in ('parts_only','top_level'):raise ValueError('mode must be parts_only/top_level')
    from pathlib import Path
    from .modeling import _find_sw_dir
    if template is None:
        install=Path(_find_sw_dir())
        template=next((p for root in (install,*install.parents) for p in (root/'lang').glob('*/bom-standard.sldbomtbt')),None)
    if not template or not Path(template).is_file():raise ValueError('Native BOM template required')
    _,_,guard=target_document(drawing_path,3)
    result=run_native(dict(guard,bom_mode=mode,template=str(template)),engine=_ENGINE)
    if result.get('ok'):
        from .bom_format import validate_bom_format
        result['format_check']=validate_bom_format(result['rows'],result['column_titles'],result['header_position'])
        result['review_required']=True
        result['ready_for_manufacture']=False
    return result
