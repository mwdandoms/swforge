"""SW2025 native GB-oriented assets/styles; evidence is read from native objects."""
from pathlib import Path
from .native_bridge import run_native,target_document

GB_STYLES={'font':'仿宋','height_series_mm':[2.5,3.5,5,7,10,14,20],
           'layers':{'GB_FRAME':(0,2),'GB_THIN':(0,0),'GB_CENTER':(4,0),'GB_HIDDEN':(1,0)}}
PAPERS={'A0':(1189,841),'A1':(841,594),'A2':(594,420),'A3':(420,297),'A4':(210,297)}
ASSETS=Path(__file__).parent/'assets'/'templates'


def gb_template_path(paper='A3'):
    if paper not in PAPERS:raise ValueError('A0..A4 required')
    p=ASSETS/('gb_'+paper.lower()+'.drwdot')
    if not p.is_file():raise FileNotFoundError('Packaged GB template not generated/accepted: '+str(p))
    return str(p)


def create_gb_template(seed_template,out_path,paper='A3'):
    if paper not in PAPERS or Path(out_path).exists():raise ValueError('Known paper and new output required')
    from .resources import document_inventory,get_session
    inv=document_inventory(get_session().sw())
    if inv['document_count']>=8:raise RuntimeError('Document limit')
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    return run_native(dict(mode='make',process_id=inv['process_id'],seed=str(seed_template),out=str(Path(out_path).resolve()),
                           width=PAPERS[paper][0]/1000,height=PAPERS[paper][1]/1000,paper=paper),engine=_ENGINE)


def _operate(path,mode):
    target=target_document(path,3)[2]
    return run_native(dict(target,mode=mode),engine=_ENGINE)


def apply_gb_styles(drawing_path):return _operate(drawing_path,'apply')


def read_gb_styles(drawing_path):return _operate(drawing_path,'read')


def set_projection(drawing_path,first_angle=True):
    if first_angle is not True:
        raise ValueError('This GB profile supports first-angle only; third-angle graphic replacement is not verified')
    target=target_document(drawing_path,3)[2]
    r=run_native(dict(target,mode='projection',first_angle=bool(first_angle)),engine=_ENGINE)
    r['ok']=bool(r.get('ok') and r.get('first_angle')==bool(first_angle) and r.get('projection_segments',0)>=6)
    return r


def validate_gb_template(path):
    from .resources import document_inventory,get_session
    if not Path(path).is_file():return {'ok':False,'missing':['template_file']}
    inv=document_inventory(get_session().sw())
    result=run_native(dict(mode='validate_template',seed=str(Path(path).resolve()),
                           process_id=inv['process_id']),engine=_ENGINE)
    required=('template','projection','font','line_style','line_width','title_block')
    result['ok']=bool(result.get('ok') and all(result['evidence'].get(k,{}).get('passed') for k in required))
    result['missing']=[k for k in required if not result.get('evidence',{}).get(k,{}).get('passed')]
    return result


_ENGINE=r'''
using System;using System.IO;using System.Collections.Generic;using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;using SolidWorks.Interop.swconst;
public class __CLASS__ {
static JavaScriptSerializer json=new JavaScriptSerializer();static IModelDoc2 md;static IDrawingDoc dr;static ILayerMgr lm;
static Dictionary<string,object> R(params object[] p){var d=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)d[(string)p[i]]=p[i+1];return d;}
static string J(object v){return System.Text.RegularExpressions.Regex.Replace(json.Serialize(v),@"[^\u0000-\u007F]",m=>"\\u"+((int)m.Value[0]).ToString("x4"));}
static void Line(double x,double y,double a,double b){if(md.SketchManager.CreateLine(x,y,0,a,b,0)==null)throw new Exception("Line failed");}
static void Text(string text,string tag,double x,double y){md.ClearSelection2(true);var n=(INote)md.InsertNote(text);if(n==null)throw new Exception("Note failed");n.TagName=tag;var a=(IAnnotation)n.GetAnnotation();a.SetLeader3(0,0,false,false,false,false);a.SetPosition2(x,y,0);var f=(ITextFormat)a.GetTextFormat(0);f.TypeFaceName="仿宋";f.CharHeight=.0035;a.SetTextFormat(0,false,f);}
static void Styles(){
 lm=(ILayerMgr)md.GetLayerManager();string[] names={"GB_FRAME","GB_THIN","GB_CENTER","GB_HIDDEN"};int[] styles={0,0,4,1},widths={2,0,0,0};
 for(int i=0;i<4;i++){var l=(ILayer)lm.GetLayer(names[i]);if(l==null){lm.AddLayer(names[i],"swforge explicit GB style",0,styles[i],widths[i]);l=(ILayer)lm.GetLayer(names[i]);}if(l==null)throw new Exception("Layer creation failed");l.Style=styles[i];l.Width=widths[i];}
 foreach(int kind in new int[]{0,1}){var f=(ITextFormat)md.GetUserPreferenceTextFormat(kind);f.TypeFaceName="仿宋";f.CharHeight=.0035;if(!md.SetUserPreferenceTextFormat(kind,f))throw new Exception("Text style write failed");}
 md.SetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swUnitSystem,(int)swUnitSystem_e.swUnitSystem_MMGS);
 if(!md.Extension.SetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterThinLineWeight,0,.00025)||!md.Extension.SetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterNormalLineWeight,0,.00035)||!md.Extension.SetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterThickLineWeight,0,.0005))throw new Exception("Document line weight write failed");
}
static object Inspect(){
 var sh=(ISheet)dr.GetCurrentSheet();double[] p=(double[])sh.GetProperties();var tags=new HashSet<string>();int graphic=0,frame=0;double minX=99,minY=99,maxX=-99,maxY=-99;var notes=new List<object>();
 for(IView v=(IView)dr.GetFirstView();v!=null;v=(IView)v.GetNextView())foreach(object o in (object[])v.GetAnnotations()??new object[0]){var n=((IAnnotation)o).GetSpecificAnnotation() as INote;if(n!=null){tags.Add(n.TagName??"");notes.Add(R("text",n.GetText(),"tag",n.TagName));}}
 foreach(IFeature f in Features()){if(f.GetTypeName2()=="ProfileFeature"||f.GetTypeName2()=="3DProfileFeature"){var sk=f.GetSpecificFeature2() as ISketch;if(sk==null)continue;foreach(object o in (object[])sk.GetSketchSegments()??new object[0]){var s=(ISketchSegment)o;if(s.Layer=="GB_PROJECTION")graphic++;if(s.Layer=="GB_FRAME"){frame++;var ln=s as ISketchLine;if(ln!=null){foreach(ISketchPoint pt in new ISketchPoint[]{(ISketchPoint)ln.GetStartPoint2(),(ISketchPoint)ln.GetEndPoint2()}){minX=Math.Min(minX,pt.X);minY=Math.Min(minY,pt.Y);maxX=Math.Max(maxX,pt.X);maxY=Math.Max(maxY,pt.Y);}}}}}}
 var fmt=(ITextFormat)md.GetUserPreferenceTextFormat(0);var layers=new List<object>();bool ls=true,lw=true;string[] names={"GB_FRAME","GB_THIN","GB_CENTER","GB_HIDDEN"};int[] st={0,0,4,1},wi={2,0,0,0};
 lm=(ILayerMgr)md.GetLayerManager();for(int i=0;i<4;i++){var l=(ILayer)lm.GetLayer(names[i]);if(l==null){ls=false;lw=false;continue;}layers.Add(R("name",names[i],"style",l.Style,"width",l.Width));ls&=l.Style==st[i];lw&=l.Width==wi[i];}
 bool paper=false;foreach(var size in new double[][]{new double[]{1.189,.841},new double[]{.841,.594},new double[]{.594,.420},new double[]{.420,.297},new double[]{.210,.297}})if(Math.Abs(p[5]-size[0])<1e-7&&Math.Abs(p[6]-size[1])<1e-7)paper=true;
 var evidence=R("template",R("verified",true,"passed",paper&&frame>=4,"detail","Native paper size and frame segments"),"projection",R("verified",true,"passed",p[4]!=0&&graphic>=6,"detail","First-angle sheet property plus graphical primitives"),"font",R("verified",true,"passed",fmt.TypeFaceName=="仿宋"&&Math.Abs(fmt.CharHeight-.0035)<1e-7,"detail","Explicit FangSong style; exact long-FangSong glyph conformity requires review"),"line_style",R("verified",true,"passed",ls),"line_width",R("verified",true,"passed",lw),"title_block",R("verified",true,"passed",tags.Contains("GB_TITLE_图样名称")&&tags.Contains("GB_TITLE_图样代号")));
 double margin=p[5]>.42?.01:.005;bool border=Math.Abs(minX-.025)<1e-7&&Math.Abs(minY-margin)<1e-7&&Math.Abs(maxX-(p[5]-margin))<1e-7&&Math.Abs(maxY-(p[6]-margin))<1e-7;
 bool zones=true;for(int i=0;i<8;i++)zones&=tags.Contains("GB_ZONE_X_"+i);for(int i=0;i<6;i++)zones&=tags.Contains("GB_ZONE_Y_"+i);
 bool fields=true;foreach(string name in new string[]{"图样名称","图样代号","材料","比例","设计","校对","审核","批准","日期","更改标记","更改文件号"})fields&=tags.Contains("GB_TITLE_"+name);
 evidence["template"]=R("verified",true,"passed",paper&&frame>=4&&border&&zones&&md.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swUnitSystem)==(int)swUnitSystem_e.swUnitSystem_MMGS,"detail","Native paper/frame bounds, 25mm binding edge, zones and MMGS units");
 evidence["title_block"]=R("verified",true,"passed",fields);
 double[] weights={md.Extension.GetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterThinLineWeight,0)*1000,md.Extension.GetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterNormalLineWeight,0)*1000,md.Extension.GetUserPreferenceDouble((int)swUserPreferenceDoubleValue_e.swPageSetupPrinterThickLineWeight,0)*1000};
 evidence["line_width"]=R("verified",true,"passed",lw&&Math.Abs(weights[0]-.25)<1e-6&&Math.Abs(weights[1]-.35)<1e-6&&Math.Abs(weights[2]-.5)<1e-6);
 return R("ok",true,"paper_mm",new double[]{p[5]*1000,p[6]*1000},"unit_system",md.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swUnitSystem),"line_weights_mm",weights,"first_angle",p[4]!=0,"projection_segments",graphic,"frame_segments",frame,"font",fmt.TypeFaceName,"char_height_mm",fmt.CharHeight*1000,"layers",layers,"notes",notes,"evidence",evidence,"ready_for_manufacture",false,"review_required",true);
}
static IEnumerable<IFeature> Features(){var todo=new Queue<IFeature>();for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())todo.Enqueue(f);int count=0;while(todo.Count>0&&count++<5000){var f=todo.Dequeue();yield return f;for(IFeature s=(IFeature)f.GetFirstSubFeature();s!=null;s=(IFeature)s.GetNextSubFeature())todo.Enqueue(s);}}
public static string Run(string request){ISldWorks sw=null;bool owned=false;try{
 var c=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));string mode=(string)c["mode"];sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));if(sw.GetProcessID()!=Convert.ToInt32(c["process_id"]))throw new Exception("SW process changed");
 if(mode=="validate_template"){
  if(sw.GetDocumentCount()>=8)throw new Exception("Document limit");
  md=(IModelDoc2)sw.NewDocument((string)c["seed"],0,0,0);if(md==null)throw new Exception("Template cannot create drawing");owned=true;dr=(IDrawingDoc)md;return J(Inspect());
 }
 if(mode=="make"){
  if(sw.GetDocumentCount()>=8)throw new Exception("Document limit");
  double w=Convert.ToDouble(c["width"]),h=Convert.ToDouble(c["height"]);md=(IModelDoc2)sw.NewDocument((string)c["seed"],12,w,h);if(md==null)throw new Exception("New drawing failed");owned=true;dr=(IDrawingDoc)md;
  var sh=(ISheet)dr.GetCurrentSheet();if(!dr.SetupSheet5(sh.GetName(),12,13,1,1,true,"",w,h,"",true))throw new Exception("Blank sheet setup failed");
  Styles();dr.EditTemplate();double margin=w>.42?.01:.005;lm.SetCurrentLayer("GB_FRAME");Line(.025,margin,w-margin,margin);Line(w-margin,margin,w-margin,h-margin);Line(w-margin,h-margin,.025,h-margin);Line(.025,h-margin,.025,margin);
  lm.SetCurrentLayer("GB_THIN");double x=w-margin-.18,y=margin;Line(x,y+.080,w-margin,y+.080);Line(x,y,x,y+.080);
  foreach(double yy in new double[]{.02,.034,.048,.062})Line(x,y+yy,w-margin,y+yy);
  Line(x+.06,y+.02,x+.06,y+.080);Line(x+.12,y+.02,x+.12,y+.080);
  string[] fields={"图样名称","图样代号","材料","比例","设计","校对","审核","批准","日期","更改标记","更改文件号"};
  for(int i=0;i<fields.Length;i++){double xx=x+(i%3)*.06,yy=y+new double[]{.077,.059,.045,.031}[i/3];Text(fields[i],"GB_LABEL_"+fields[i],xx+.002,yy);Text("\""+fields[i]+"\"","GB_TITLE_"+fields[i],xx+.002,yy-.006);}
  for(int i=0;i<8;i++)Text((i+1).ToString(),"GB_ZONE_X_"+i,.025+(w-margin-.025)*(i+.5)/8,h-.001);
  for(int i=0;i<6;i++)Text(((char)('A'+i)).ToString(),"GB_ZONE_Y_"+i,.004,margin+(h-2*margin)*(i+.5)/6);
  lm.AddLayer("GB_PROJECTION","first angle graphic",0,0,0);lm.SetCurrentLayer("GB_PROJECTION");double px=x+.006,py=y+.006;
  Line(px,py,px+.01,py+.002);Line(px+.01,py+.002,px+.01,py+.01);Line(px+.01,py+.01,px,py+.012);Line(px,py+.012,px,py);
  md.SketchManager.CreateCircleByRadius(px+.02,py+.006,0,.006);md.SketchManager.CreateCircleByRadius(px+.02,py+.006,0,.004);
  string format=Path.ChangeExtension((string)c["out"],".slddrt");if(File.Exists(format))throw new Exception("Format already exists");if(!sh.SaveFormat(format))throw new Exception("Format save failed");
  dr.EditSheet();md.ForceRebuild3(false);int err=0,warn=0;if(!md.Extension.SaveAs((string)c["out"],0,1,null,ref err,ref warn)||err!=0)throw new Exception("Template save failed "+err);
 }else{
  md=(IModelDoc2)sw.ActiveDoc;if(md==null||md.GetType()!=3||md.GetPathName()!=(string)c["path"]||sw.GetProcessID()!=Convert.ToInt32(c["process_id"]))throw new Exception("Drawing ownership changed");dr=(IDrawingDoc)md;if(mode=="apply")Styles();
  if(mode=="projection"){
   var sh=(ISheet)dr.GetCurrentSheet();double[] p=(double[])sh.GetProperties();bool first=Convert.ToBoolean(c["first_angle"]);
   if(!dr.SetupSheet5(sh.GetName(),(int)p[0],(int)p[1],p[2],p[3],first,sh.GetTemplateName(),p[5],p[6],"",false))throw new Exception("Projection property write failed");
   lm=(ILayerMgr)md.GetLayerManager();if(lm.GetLayer("GB_PROJECTION")==null){
    dr.EditTemplate();lm.AddLayer("GB_PROJECTION","projection graphic",0,0,0);lm.SetCurrentLayer("GB_PROJECTION");double x=p[5]-.06,y=.015;
    double tx=first?x:x+.02,cx=first?x+.02:x;Line(tx,y,tx+.01,y+.002);Line(tx+.01,y+.002,tx+.01,y+.01);Line(tx+.01,y+.01,tx,y+.012);Line(tx,y+.012,tx,y);md.SketchManager.CreateCircleByRadius(cx,y+.006,0,.006);md.SketchManager.CreateCircleByRadius(cx,y+.006,0,.004);dr.EditSheet();
   }md.ForceRebuild3(false);
  }
 }
 return J(Inspect());
 }catch(Exception e){return J(R("ok",false,"error",e.ToString()));}
 finally{if(owned&&md!=null)sw.CloseDoc(md.GetTitle());}
}
}
'''
