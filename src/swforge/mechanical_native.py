"""Typed implementations of features not covered by PartBuilder; shared runner/helpers."""


def engine():
    from .modeling import _CS_TEMPLATE
    helpers=_CS_TEMPLATE[_CS_TEMPLATE.index('    static IFeature Datum('):_CS_TEMPLATE.index('    static IBody2 BodyOf(')]
    return _ENGINE.replace('__SKETCH_HELPERS__',helpers)


_ENGINE=r'''
using System;using System.IO;using System.Linq;using System.Collections;using System.Collections.Generic;
using System.Runtime.InteropServices;using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;using SolidWorks.Interop.swconst;
public class __CLASS__ {
 const double MM=.001;const bool MERGE=true;
 static ISldWorks sw;static IModelDoc2 md;static IMathUtility math;
 static JavaScriptSerializer json=new JavaScriptSerializer(){MaxJsonLength=16777216};
 static Dictionary<string,object> cmd,plan,p;
 static Dictionary<string,object> Row(params object[] a){var r=new Dictionary<string,object>();for(int i=0;i<a.Length;i+=2)r[(string)a[i]]=a[i+1];return r;}
 static string S(Dictionary<string,object>d,string key){return d.ContainsKey(key)?Convert.ToString(d[key]):"";}
 static double N(Dictionary<string,object>d,string key){return Convert.ToDouble(d[key]);}
 static object[] A(object o){return ((IEnumerable)o).Cast<object>().ToArray();}
 static double[] D(object o){return A(o).Select(Convert.ToDouble).ToArray();}
 static DispatchWrapper[] W(object[] a){return a.Select(x=>new DispatchWrapper(x)).ToArray();}
 __SKETCH_HELPERS__
 static void Save(string path){int e=0,w=0;if(!md.Extension.SaveAs(path,0,1,null,ref e,ref w)||e!=0)throw new Exception("Save failed "+e+": "+path);}
 static void NewPart(){
  if(sw.GetDocumentCount()>=Convert.ToInt32(cmd["max_documents"]))throw new Exception("Document limit reached");
  md=(IModelDoc2)sw.NewDocument(S(cmd,"template"),0,0,0);if(md==null)throw new Exception("New part failed");
  md.SketchManager.AddToDB=true;
 }
 static List<Dictionary<string,object>> cuts=new List<Dictionary<string,object>>();
 static HashSet<string> seen=new HashSet<string>();
 static void Visit(IFeature f){
  if(!seen.Add(f.Name+"|"+f.GetTypeName2()))return;
  if(f.GetTypeName2()=="CutListFolder"){
   IBodyFolder folder=(IBodyFolder)f.GetSpecificFeature2();int count=folder.GetBodyCount();
   if(count>0){
    var props=new Dictionary<string,object>();var manager=f.CustomPropertyManager;
    object[] names=(object[])manager.GetNames();if(names!=null)foreach(object item in names){string raw="",resolved="";bool wr=false,link=false;manager.Get6((string)item,false,out raw,out resolved,out wr,out link);props[(string)item]=String.IsNullOrEmpty(resolved)?raw:resolved;}
    cuts.Add(Row("folder",f.Name,"quantity",count,"properties",props,"bodies",((object[])folder.GetBodies()).Select(x=>((IBody2)x).Name).ToArray()));
   }
  }
  for(IFeature sub=(IFeature)f.GetFirstSubFeature();sub!=null;sub=(IFeature)sub.GetNextSubFeature())Visit(sub);
 }
 static void UpdateCuts(){
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())if(f.GetTypeName2()=="SolidBodyFolder"){
   IBodyFolder folder=(IBodyFolder)f.GetSpecificFeature2();folder.SetAutomaticCutList(true);folder.SetAutomaticUpdate(true);folder.UpdateCutList();
  }
 }
 static object Inspect(){
  if(md.GetType()!=1)throw new Exception("Part required");
  var features=new List<object>();var circles=new List<object>();var vertices=new List<object>();
  for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature()){
   bool warning=false;int err=f.GetErrorCode2(out warning);
   var row=Row("name",f.Name,"type",f.GetTypeName2(),"error",err);features.Add(row);
   if(f.GetTypeName2()=="CirPattern"){
    var pattern=(ICircularPatternFeatureData)f.GetDefinition();row["instances"]=pattern.TotalInstances;row["spacing_rad"]=pattern.Spacing;
   }
  }
  object[] bodies=(object[])((IPartDoc)md).GetBodies2(0,false);if(bodies==null||bodies.Length==0)throw new Exception("No solid body");
  var bodyRows=new List<object>();
  foreach(object item in bodies){
   IBody2 body=(IBody2)item;double[] mass=(double[])body.GetMassProperties(1);
   bodyRows.Add(Row("name",body.Name,"volume_mm3",mass[3]*1e9,"bbox_mm",((double[])body.GetBodyBox()).Select(x=>x*1000).ToArray()));
   foreach(object vertex in (object[])body.GetVertices())vertices.Add(((double[])((IVertex)vertex).GetPoint()).Select(x=>x*1000).ToArray());
   foreach(object faceObject in (object[])body.GetFaces()){
    IFace2 face=(IFace2)faceObject;ISurface surface=(ISurface)face.GetSurface();
    if(surface.IsCylinder()){double[] c=(double[])surface.CylinderParams;circles.Add(Row("center_mm",c.Take(3).Select(x=>x*1000).ToArray(),"axis",c.Skip(3).Take(3).ToArray(),"radius_mm",c[6]*1000));}
   }
  }
  IMassProperty mp=(IMassProperty)md.Extension.CreateMassProperty();mp.UseSystemUnits=true;
  double kg=mp.Mass,volume=mp.Volume;string database="";string material=((IPartDoc)md).GetMaterialPropertyName2("",out database);
  cuts.Clear();seen.Clear();for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())Visit(f);
  return Row("ok",true,"path",md.GetPathName(),"configuration",md.ConfigurationManager.ActiveConfiguration.Name,
   "features",features,"bodies",bodyRows,"body_count",bodies.Length,"cut_list",cuts,"cylinders",circles,"vertices_mm",vertices,
   "volume_mm3",volume*1e9,"mass_kg",kg,"density_kg_m3",kg/volume,"material",material,"modified",md.GetSaveFlag());
 }
 static void Frame(){
  double s=N(p,"section")*MM,t=N(p,"wall")*MM;
  // 素材库模式：轮廓是库里的现成 .SLDLFP，直接拿来用，不现场生成。
  // 这才能保证出来的是真型材截面（圆角、壁厚、内圆角都对），不是拼板冒充。
  if(S(cmd,"profile_source")!="library"){
   NewPart();ISketch sketch=Begin("z",0);
   md.SketchManager.CreateCornerRectangle(-s/2,-s/2,0,s/2,s/2,0);
   md.SketchManager.CreateCornerRectangle(-s/2+t,-s/2+t,0,s/2-t,s/2-t,0);
   IFeature profileSketch=End(sketch);profileSketch.Name="SWFORGE_SHS_PROFILE";profileSketch.Select2(false,0);
   md.Extension.CustomPropertyManager[""].Add3("Description",30,"SHS "+N(p,"section")+"x"+N(p,"section")+"x"+N(p,"wall"),2);
   md.SketchManager.AddToDB=false;Save(S(cmd,"profile"));sw.CloseDoc(md.GetTitle());md=null;
  }
  NewPart();var weld=(IFeature)md.FeatureManager.InsertWeldmentFeature();if(weld==null)throw new Exception("Native weldment feature failed");
  md.SketchManager.Insert3DSketch(true);var lines=new List<object>();
  foreach(object pair in A(plan["lines_mm"])){
   object[] pts=A(pair);double[] a=D(pts[0]),b=D(pts[1]);
   var line=(ISketchSegment)md.SketchManager.CreateLine(a[0]*MM,a[1]*MM,a[2]*MM,b[0]*MM,b[1]*MM,b[2]*MM);
   if(line==null)throw new Exception("Path line failed");lines.Add(line);
  }
  md.SketchManager.Insert3DSketch(true);md.ClearSelection2(true);
  var groups=new List<object>();
  foreach(object line in lines){var group=(IStructuralMemberGroup)md.FeatureManager.CreateStructuralMemberGroup();group.Segments=W(new object[]{line});group.Angle=0;group.ApplyCornerTreatment=false;groups.Add(group);}
  IFeature structure=(IFeature)md.FeatureManager.InsertStructuralWeldment5(S(cmd,"profile"),1,false,W(groups.ToArray()),"");
  if(structure==null)throw new Exception("Native structural member feature failed");structure.Name="SWFORGE_FRAME_MEMBERS";
  object[] bodies=(object[])((IPartDoc)md).GetBodies2(0,false);
  int expectMembers=plan.ContainsKey("member_count")?Convert.ToInt32(plan["member_count"]):12;
  if(bodies==null||bodies.Length!=expectMembers)throw new Exception("Expected "+expectMembers+" separate members, got "+(bodies==null?0:bodies.Length));
  for(int i=0;i<bodies.Length;i++)((IBody2)bodies[i]).Name="MEMBER_"+(i+1).ToString("00");
  md.SketchManager.AddToDB=false;md.ForceRebuild3(false);UpdateCuts();
 }
 static void Circle(double radius){ISketch sk=Begin("z",0);double[] c=Local(sk,0,0,0);md.SketchManager.CreateCircleByRadius(c[0],c[1],0,radius*MM);}
 static IFeature Disk(double radius,double hole,double width,string name){
  ISketch sk=Begin("z",0);double[] c=Local(sk,0,0,0);
  md.SketchManager.CreateCircleByRadius(c[0],c[1],0,radius*MM);
  md.SketchManager.CreateCircleByRadius(c[0],c[1],0,hole*MM/2);
  End(sk);IFeature f=Extrude(sk,"z",0,width);if(f==null)throw new Exception("Disk/hub extrusion failed");f.Name=name;return f;
 }
 static void Gear(){
  NewPart();double rf=N(plan,"root_diameter_mm")/2,bore=N(p,"bore"),width=N(p,"face_width");
  Disk(rf,bore,width,"SWFORGE_ROOT_DISK");
  ISketch sk=Begin("z",0);object[] pts=A(plan["seed_polygon_mm"]);
  for(int i=0;i<pts.Length;i++){
   double[] a=D(pts[i]),b=D(pts[(i+1)%pts.Length]);a=Local(sk,a[0],a[1],0);b=Local(sk,b[0],b[1],0);
   if(md.SketchManager.CreateLine(a[0],a[1],0,b[0],b[1],0)==null)throw new Exception("Tooth edge failed");
  }
  End(sk);IFeature tooth=Extrude(sk,"z",0,width);if(tooth==null)throw new Exception("Seed tooth extrusion failed");tooth.Name="SWFORGE_INVOLUTE_TOOTH";
  md.ClearSelection2(true);Datum("x").Select2(false,0);Datum("y").Select2(true,0);
  if(!md.InsertAxis2(true))throw new Exception("Gear axis creation failed");
  IFeature axis=null;for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())if(f.GetTypeName2()=="RefAxis")axis=f;
  if(axis==null)throw new Exception("Gear axis missing");axis.Name="SWFORGE_GEAR_AXIS";
  md.ClearSelection2(true);axis.Select2(false,1);tooth.Select2(true,4);
  IFeature pattern=(IFeature)md.FeatureManager.FeatureCircularPattern4(Convert.ToInt32(p["teeth"]),2*Math.PI,false,"",false,true,false);
  if(pattern==null)throw new Exception("Native circular tooth pattern failed");pattern.Name="SWFORGE_TOOTH_PATTERN";
  if(N(p,"hub_diameter")>0)Disk(N(p,"hub_diameter")/2,bore,width+N(p,"hub_length"),"SWFORGE_HUB");
  md.SketchManager.AddToDB=false;md.ForceRebuild3(false);
  md.ClearSelection2(true);axis.Select2(false,0);md.BlankRefGeom();md.ClearSelection2(true);
 }
 static object Build(){
  string output=S(cmd,"out");
  // 素材库模式下轮廓是库里现成的 .SLDLFP，存在才是正常的，不能当冲突
  bool profileIsInput=S(cmd,"profile_source")=="library";
  if(File.Exists(output)||(!profileIsInput&&File.Exists(S(cmd,"profile"))))throw new Exception("Output collision");
  bool saved=false;
  try{
   if(S(plan,"kind")=="shs_frame")Frame();else Gear();
   IPartDoc pd=(IPartDoc)md;pd.SetMaterialPropertyName2("",S(cmd,"material_db"),S(cmd,"material"));md.ForceRebuild3(false);
   if(S(plan,"kind")=="shs_frame")UpdateCuts();
   var props=md.Extension.CustomPropertyManager[""];props.Add3("SWFORGE_KIND",30,S(plan,"kind"),2);
   foreach(var kv in p)props.Add3("SWFORGE_"+kv.Key,30,Convert.ToString(kv.Value,System.Globalization.CultureInfo.InvariantCulture),2);
   var got=(Dictionary<string,object>)Inspect();
   if(S(got,"material")!=S(cmd,"material")||Math.Abs(N(got,"density_kg_m3")-N(cmd,"density"))>1)throw new Exception("Material/density mismatch");
   // 素材库轮廓是真实冷弯/热轧截面，带内圆角，比理想尖角环少 1% 左右的料。
   // 库模式放宽容差，并把实际偏差写进失败信息，不能因为"过于精确"而判失败。
   bool libProfile=S(cmd,"profile_source")=="library";
   double tolerance=S(plan,"kind")=="shs_frame"?(libProfile?0.06:1e-5):0.001;
   double volRatio=N(got,"volume_mm3")/N(plan,"expected_volume_mm3");
   if(Math.Abs(volRatio-1)>tolerance)throw new Exception("Independent volume check failed: "+got["volume_mm3"]+" vs "+plan["expected_volume_mm3"]+" ratio="+volRatio.ToString("F6"));
   foreach(Dictionary<string,object> f in (List<object>)got["features"])if(Convert.ToInt32(f["error"])!=0)throw new Exception("Native feature error: "+f["name"]+"="+f["error"]);
    if(S(plan,"kind")=="shs_frame"&&cuts.Sum(x=>Convert.ToInt32(x["quantity"]))!=(plan.ContainsKey("member_count")?Convert.ToInt32(plan["member_count"]):12))throw new Exception("Cut list quantity mismatch");
   if(File.Exists(output))throw new Exception("Output occupied before save");
   md.ShowNamedView2("",7);md.ViewZoomtofit2();md.ClearSelection2(true);Save(output);saved=true;
   got["path"]=output;got["modified"]=md.GetSaveFlag();got["plan"]=plan;
   return got;
  }finally{
   if(md!=null){try{md.SketchManager.AddToDB=false;}catch{}if(!saved||!Convert.ToBoolean(cmd["keep_open"]))sw.CloseDoc(md.GetTitle());}
  }
 }
 static List<object> TableCells(ITableAnnotation table){
  var rows=new List<object>();for(int r=0;r<table.RowCount;r++){var cells=new List<string>();for(int c=0;c<table.ColumnCount;c++)cells.Add(table.get_Text2(r,c,false));rows.Add(cells);}return rows;
 }
 static object Drawing(){
  IDrawingDoc drawing=(IDrawingDoc)md;IView view=(IView)((IView)drawing.GetFirstView()).GetNextView();
  var meta=(Dictionary<string,object>)cmd["metadata"];var par=(Dictionary<string,object>)meta["parameters"];
  IModelDoc2 reference=(IModelDoc2)view.ReferencedDocument;
  if(reference==null)throw new Exception("Drawing model is unresolved");
  ICustomPropertyManager properties=reference.Extension.CustomPropertyManager[""];
  foreach(var parameter in par){
   string raw="",value="";bool resolved=false,linked=false;properties.Get6("SWFORGE_"+parameter.Key,false,out raw,out value,out resolved,out linked);
   double numeric=0;
   if(!Double.TryParse(String.IsNullOrEmpty(value)?raw:value,System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out numeric)||Math.Abs(numeric-Convert.ToDouble(parameter.Value))>1e-8)throw new Exception("Parameter table differs from native model: "+parameter.Key);
  }
  bool sectionReplaced=false;
  if(S(cmd,"section_name")!=""){
   IView section=null;IView legacy=(IView)((IView)view.GetNextView()).GetNextView();
   for(IView v=view;v!=null;v=(IView)v.GetNextView())if(v.Name==S(cmd,"section_name"))section=v;
   if(section==null||legacy==null||legacy.Name==section.Name)throw new Exception("Section replacement targets missing");
   object destination=legacy.Position;section.RemoveAlignment();section.PositionLocked=false;section.Position=destination;
   md.ClearSelection2(true);
   if(!md.Extension.SelectByID2(legacy.Name,"DRAWINGVIEW",0,0,0,false,0,null,0)||!md.Extension.DeleteSelection2(0))throw new Exception("Cannot replace redundant right view with section");
   md.ForceRebuild3(false);sectionReplaced=true;
  }
  ITableAnnotation table=null;int balloons=0;
  if(S(meta,"kind")=="shs_frame"){
   string root=Path.GetDirectoryName(typeof(ISldWorks).Assembly.Location);
   string app=Directory.Exists(Path.Combine(root,"lang"))?root:Path.GetFullPath(Path.Combine(root,"../.."));
   string template=Path.Combine(app,"lang/english/cut list.sldwldtbt");
   if(!File.Exists(template))template=Directory.GetFiles(Path.Combine(app,"lang"),"*.sldwldtbt",SearchOption.AllDirectories).FirstOrDefault();
   if(template==null)throw new Exception("No native weldment cut-list table template found");
   int activateError=0;sw.ActivateDoc3(md.GetPathName(),false,0,ref activateError);
   md.ClearSelection2(true);md.Extension.SelectByID2(view.Name,"DRAWINGVIEW",0,0,0,false,0,null,0);
   drawing.EditSheet();
   var cut=(IWeldmentCutListAnnotation)view.InsertWeldmentTable(false,.285,.135,1,"","");
   if(cut==null)throw new Exception("Native weldment table insertion failed: "+view.ReferencedConfiguration);table=(ITableAnnotation)cut;
   var keep=new HashSet<string>(new string[]{"\u9879\u76ee\u53f7","\u6570\u91cf","\u957f\u5ea6","\u8bf4\u660e","Material","ITEM NO.","QTY.","LENGTH","DESCRIPTION","MATERIAL"},StringComparer.OrdinalIgnoreCase);
   for(int c=table.ColumnCount-1;c>=0;c--)if(!keep.Contains(table.get_Text2(0,c,false)))table.DeleteColumn2(c,false);
   for(int c=0;c<table.ColumnCount;c++)table.SetColumnWidth(c,c==3?.035:.019,0);
   for(IView v=view;v!=null;v=(IView)v.GetNextView()){
    md.ClearSelection2(true);md.Extension.SelectByID2(v.Name,"DRAWINGVIEW",0,0,0,false,0,null,0);
    var options=drawing.CreateAutoBalloonOptions();options.IgnoreMultiple=true;
    object[] notes=(object[])drawing.AutoBalloon5(options);balloons+=notes==null?0:notes.Length;
    if(notes!=null){double[] outline=(double[])v.GetOutline();for(int i=0;i<notes.Length;i++){
     IAnnotation annotation=(IAnnotation)((INote)notes[i]).GetAnnotation();
     annotation.SetPosition2(outline[2]+.012,outline[3]-.008-.014*i,0);
    }}
   }
  }else{
   // Smooth only the artificial near-tangent axial facet edges in side projections.
   // Real root/tip corners and the front involute silhouette remain visible.
   for(IView side=(IView)view.GetNextView();side!=null;side=(IView)side.GetNextView()){
    object[] edges=(object[])side.GetVisibleEntities2(null,1);md.ClearSelection2(true);int selected=0;
    if(edges!=null)foreach(object item in edges){
     IEdge edge=(IEdge)item;ICurve curve=(ICurve)edge.GetCurve();if(!curve.IsLine())continue;
     double[] line=(double[])curve.LineParams;if(Math.Abs(line[5])<.999)continue;
     object[] faces=(object[])edge.GetTwoAdjacentFaces2();if(faces==null||faces.Length!=2||faces[0]==null||faces[1]==null)continue;
     IFace2 a=(IFace2)faces[0],b=(IFace2)faces[1];
     if(!((ISurface)a.GetSurface()).IsPlane()||!((ISurface)b.GetSurface()).IsPlane())continue;
     double[] na=(double[])a.Normal,nb=(double[])b.Normal;
     double dot=Math.Abs(na[0]*nb[0]+na[1]*nb[1]+na[2]*nb[2]);
     if(dot>Math.Cos(5*Math.PI/180)&&side.SelectEntity(edge,true))selected++;
    }
    if(selected>0)drawing.HideEdge();md.ClearSelection2(true);
   }
   md.ClearSelection2(true);drawing.ActivateView("");
   table=(ITableAnnotation)md.Extension.InsertGeneralTableAnnotation(false,.285,.135,1,"",par.Count+1,2);
   if(table==null)throw new Exception("Gear parameter table insertion failed");
   table.set_Text2(0,0,false,"GEAR PARAMETER");table.set_Text2(0,1,false,"VALUE (mm / deg)");
   int i=1;foreach(var item in par){table.set_Text2(i,0,false,item.Key);table.set_Text2(i++,1,false,Convert.ToString(item.Value,System.Globalization.CultureInfo.InvariantCulture));}
  }
  md.ClearSelection2(true);drawing.ActivateView("");table.Anchored=false;table.AnchorType=1;
  for(int c=0;c<table.ColumnCount;c++)table.SetColumnWidth(c,S(meta,"kind")=="spur_gear"?(c==0?.045:.027):(c==3?.035:.019),0);
  IAnnotation tableAnnotation=(IAnnotation)table.GetAnnotation();
  if(!tableAnnotation.SetPosition2(.285,.135,0))throw new Exception("Table positioning rejected");
  double[] tablePosition=(double[])tableAnnotation.GetPosition();
  if(Math.Abs(tablePosition[0]-.285)>1e-6||Math.Abs(tablePosition[1]-.135)>1e-6)throw new Exception("Table position readback differs");
  INote note=(INote)md.InsertNote(S(meta,"kind")=="shs_frame"?"NATIVE SHS FRAME / SQUARE BUTT ENDS\nNo weld size/process inferred. Engineering review required.":"UNSHIFTED INVOLUTE SPUR GEAR\nRadial root transition, not generated hob trochoid.\nGeometry demo; strength/mesh quality not certified.");
  if(note==null)throw new Exception("Engineering scope note failed");
  IAnnotation noteAnnotation=(IAnnotation)note.GetAnnotation();ITextFormat format=(ITextFormat)noteAnnotation.GetTextFormat(0);format.CharHeight=.0025;noteAnnotation.SetTextFormat(0,false,format);noteAnnotation.SetPosition2(.04,.03,0);
  md.ForceRebuild3(false);int e=0,w=0;if(!md.Save3(1,ref e,ref w)||e!=0)throw new Exception("Drawing save failed");md.ViewZoomtofit2();
  double tableWidth=0,tableHeight=0;
  for(int i=0;i<table.ColumnCount;i++)tableWidth+=table.GetColumnWidth(i);
  for(int i=0;i<table.RowCount;i++)tableHeight+=table.GetRowHeight(i);
  double[] tableBounds=new double[]{tablePosition[0],tablePosition[1]-tableHeight,tablePosition[0]+tableWidth,tablePosition[1]};
  if(tableBounds[0]<.025||tableBounds[1]<.060||tableBounds[2]>.415||tableBounds[3]>.292)throw new Exception("Table outside safe drawing region");
  return Row("ok",true,"table_rows",table.RowCount,"table_columns",table.ColumnCount,"table_cells",TableCells(table),"table_type",table.Type,"table_bounds_m",tableBounds,"balloons",balloons,"configuration",view.ReferencedConfiguration,"section_replaces_right_view",sectionReplaced);
 }
 public static string Run(string request){
  bool progressChanged=false,previousProgress=false;
  try{
   cmd=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));
   sw=(ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"));
   if(sw.GetProcessID()!=Convert.ToInt32(cmd["process_id"]))throw new Exception("SW process changed");
   if(typeof(ISldWorks).Assembly.GetName().Version.Major!=Int32.Parse(sw.RevisionNumber().Split('.')[0]))throw new Exception("Interop version mismatch");
   previousProgress=sw.CommandInProgress;sw.CommandInProgress=true;progressChanged=true;
   math=(IMathUtility)sw.GetMathUtility();object result;
   if(S(cmd,"mode")=="build"){
    plan=(Dictionary<string,object>)cmd["plan"];p=(Dictionary<string,object>)plan["parameters"];result=Build();
   }else{
    md=(IModelDoc2)sw.ActiveDoc;
    if(md==null||!String.Equals(md.GetPathName(),S(cmd,"path"),StringComparison.OrdinalIgnoreCase))throw new Exception("Active document changed");
    result=S(cmd,"mode")=="inspect"?Inspect():Drawing();
   }
   return json.Serialize(result);
  }catch(Exception ex){return json.Serialize(Row("ok",false,"error",ex.ToString()));}
  finally{if(progressChanged){try{sw.CommandInProgress=previousProgress;}catch{}}}
 }
}
'''
