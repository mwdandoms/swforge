"""SolidWorks sketch dimensions for PartBuilder's rectangular and round primitives."""

PROFILE_KINDS = {
    "Box": "rectangle",
    "CutBox": "rectangle",
    "Cylinder": "circle",
    "Hole": "circle",
    "Tube": "tube",
}

CS = r"""
    static void RequireDimension(bool ok,string detail) {
        if(!ok) throw new Exception("Editable dimension: "+detail);
    }
    static string DimensionValue(double value) {
        return value.ToString("R",System.Globalization.CultureInfo.InvariantCulture);
    }
    static double[] SketchToModel(ISketch sketch,double x,double y) {
        var point=(IMathPoint)math.CreatePoint(new[]{x,y,0.0});
        return (double[])point.IMultiplyTransform(sketch.ModelToSketchTransform.IInverse()).ArrayData;
    }
    static void NameDimension(IDisplayDimension display,string name,double expected) {
        RequireDimension(display!=null,name+" was not created");
        var dimension=(IDimension)display.GetDimension2(0);
        RequireDimension(dimension.DrivenState==2 && !dimension.ReadOnly &&
            Math.Abs(dimension.SystemValue-expected)<1e-8,name+" is not a driving dimension at nominal value (state="+dimension.DrivenState+", actual="+dimension.SystemValue+", expected="+expected+")");
        dimension.Name=name;
        L("SWFORGE_DRIVING_DIM name="+dimension.FullName+" mm="+DimensionValue(expected/MM));
    }
    static void PinSketchPoint(ISketchPoint point) {
        if(Math.Abs(point.X)+Math.Abs(point.Y)<1e-8) return;
        md.ClearSelection2(true);
        RequireDimension(point.Select4(false,null),"select anchor point");
        md.SketchAddConstraints("sgFIXED");
    }
    static void DimensionSketchOffset(ISketch sk,ISketchPoint point,int axis) {
        double value=axis==0?point.X:point.Y;
        var origin=SketchToModel(sk,0,0);
        md.ClearSelection2(true);
        RequireDimension(point.Select4(false,null),"select circle center");
        RequireDimension(md.Extension.SelectByID2("", "EXTSKETCHPOINT",
            origin[0],origin[1],origin[2],true,0,null,0),"select sketch origin");
        if(Math.Abs(value)<1e-9) {
            md.SketchAddConstraints(axis==0?"sgVERTICAL":"sgHORIZONTAL");
            return;
        }
        var label=SketchToModel(sk,point.X/2+(axis==1?.008:0),point.Y/2+(axis==0?.008:0));
        var display=(IDisplayDimension)(axis==0?md.AddHorizontalDimension2(label[0],label[1],label[2]):
            md.AddVerticalDimension2(label[0],label[1],label[2]));
        NameDimension(display,axis==0?"CenterOffsetX":"CenterOffsetY",Math.Abs(value));
    }
    static void DimensionRectangleAxis(ISketch sk,ISketchSegment[] lines,int axis,string name) {
        var horizontal=axis==0;
        var segment=lines.First(s=>{
            var line=(ISketchLine)s;
            var a=(ISketchPoint)line.GetStartPoint2();
            var b=(ISketchPoint)line.GetEndPoint2();
            return Math.Abs(horizontal?a.Y-b.Y:a.X-b.X)<1e-8;
        });
        var u=(ISketchPoint)((ISketchLine)segment).GetStartPoint2();
        var v=(ISketchPoint)((ISketchLine)segment).GetEndPoint2();
        var label=SketchToModel(sk,(u.X+v.X)/2+(horizontal?0:.006),(u.Y+v.Y)/2-(horizontal?.006:0));
        md.ClearSelection2(true);
        RequireDimension(segment.Select4(false,null),"select edge for "+name);
        var display=(IDisplayDimension)(horizontal?md.AddHorizontalDimension2(label[0],label[1],label[2]):
            md.AddVerticalDimension2(label[0],label[1],label[2]));
        NameDimension(display,name,segment.GetLength());
    }
    static void DimensionProfile(IFeature feature,string kind) {
        var profile=(IFeature)feature.GetFirstSubFeature();
        while(profile!=null && profile.GetTypeName2()!="ProfileFeature")
            profile=(IFeature)profile.GetNextSubFeature();
        RequireDimension(profile!=null,feature.Name+" has no profile");
        var sk=(ISketch)profile.GetSpecificFeature2();
        var segments=((object[])sk.GetSketchSegments()).Cast<ISketchSegment>()
                       .Where(s=>!s.ConstructionGeometry).ToArray();
        md.ClearSelection2(true);
        RequireDimension(profile.Select2(false,0),"select "+profile.Name);
        md.EditSketch();
        RequireDimension(md.GetActiveSketch2()!=null,"edit "+profile.Name);
        try {
            if(kind=="rectangle") {
                RequireDimension(segments.Length==4 && segments.All(s=>s.GetType()==0),feature.Name);
                // CreateCornerRectangle can infer equal sides for a square.
                // Width/height are independent unless the recipe explicitly links them.
                var relations=(ISketchRelationManager)sk.RelationManager;
                foreach(object item in (object[])relations.GetRelations(0)??new object[0]) {
                    var relation=(ISketchRelation)item;
                    if(relation.GetRelationType()==(int)swConstraintType_e.swConstraintType_SAMELENGTH) {
                        RequireDimension(relations.DeleteRelation((SketchRelation)relation),"remove inferred equal sides");
                        L("SWFORGE_EDITABLE removed_inferred_equal_sides=True");
                    }
                }
                // AddToDB bypasses inferencing. Keep each rectangle edge aligned
                // before solving equal-length sides independently (square profiles).
                foreach(var segment in segments) {
                    var line=(ISketchLine)segment;
                    var a=(ISketchPoint)line.GetStartPoint2();
                    var b=(ISketchPoint)line.GetEndPoint2();
                    bool horizontal=Math.Abs(a.Y-b.Y)<1e-8;
                    md.ClearSelection2(true);
                    RequireDimension(segment.Select4(false,null),"select rectangle orientation");
                    md.SketchAddConstraints(horizontal?"sgHORIZONTAL":"sgVERTICAL");
                }
                var point=segments.SelectMany(s=>new[]{(ISketchPoint)((ISketchLine)s).GetStartPoint2(),
                                                       (ISketchPoint)((ISketchLine)s).GetEndPoint2()})
                                  .OrderBy(p=>p.Y).ThenBy(p=>p.X).First();
                PinSketchPoint(point);
                DimensionRectangleAxis(sk,segments,0,"ProfileWidth");
                DimensionRectangleAxis(sk,segments,1,"ProfileHeight");
            } else if(kind=="circle") {
                RequireDimension(segments.Length==1 && segments[0].GetType()==1,feature.Name);
                var arc=(ISketchArc)segments[0];
                var center=(ISketchPoint)arc.GetCenterPoint2();
                if(Math.Abs(center.X)+Math.Abs(center.Y)>1e-8) {
                    DimensionSketchOffset(sk,center,0);
                    DimensionSketchOffset(sk,center,1);
                }
                double r=arc.GetRadius();
                var label=SketchToModel(sk,center.X+r+.006,center.Y+r+.006);
                md.ClearSelection2(true);
                RequireDimension(segments[0].Select4(false,null),"select diameter");
                NameDimension((IDisplayDimension)md.AddDiameterDimension2(label[0],label[1],label[2]),"Diameter",2*r);
            } else {
                RequireDimension(segments.Length==8 && segments.All(s=>s.GetType()==0),feature.Name);
                var origin=SketchToModel(sk,0,0);
                RequireDimension(md.Extension.SelectByID2("", "EXTSKETCHPOINT",
                    origin[0],origin[1],origin[2],false,0,null,0),"select tube datum");
                object datum=((ISelectionMgr)md.SelectionManager).GetSelectedObject6(1,-1);
                RequireDimension(datum!=null,"read tube datum");
                md.ClearSelection2(true);
                int status=md.SketchManager.FullyDefineSketch(true,true,2|4|8|512,true,0,datum,0,datum,1,1);
                RequireDimension(status==0 && sk.GetConstrainedStatus()==2,"define tube profile "+feature.Name);
            }
        } finally {
            md.ClearSelection2(true);
            md.InsertSketch2(true);
        }
        int drivers=0;
        for(var d=(IDisplayDimension)profile.GetFirstDisplayDimension();d!=null;
            d=(IDisplayDimension)profile.GetNextDisplayDimension(d)) {
            var parameter=(IDimension)d.GetDimension2(0);
            if(parameter.DrivenState==2 && !parameter.ReadOnly) drivers++;
        }
        RequireDimension(drivers>=(kind=="rectangle"?2:1),"read driving dimensions for "+feature.Name);
        L("SWFORGE_EDITABLE feature="+feature.Name+" profile="+profile.Name+" driving="+drivers);
    }
    static double[][] DimensionBodySnapshot() {
        return ((object[])((IPartDoc)md).GetBodies2(0,false)).Cast<IBody2>().Select(body=>{
            var box=(double[])body.GetBodyBox();
            return box.Select(v=>v/MM).Concat(new[]{Volume(body)*1e9}).ToArray();
        }).ToArray();
    }
    static void AddEditableDimensions(string[] tags,string[] kinds) {
        var before=DimensionBodySnapshot();
        var input=(int)swUserPreferenceToggle_e.swInputDimValOnCreate;
        const int overDefinitionPrompt=100;
        bool oldInput=application.GetUserPreferenceToggle(input);
        bool oldPrompt=application.GetUserPreferenceToggle(overDefinitionPrompt);
        try {
            application.SetUserPreferenceToggle(input,false);
            application.SetUserPreferenceToggle(overDefinitionPrompt,false);
            var features=((object[])md.FeatureManager.GetFeatures(true)).Cast<IFeature>().ToArray();
            for(int i=0;i<tags.Length;i++) {
                // A later cut may reassign sources[tag] to the cut. Read the original feature by name.
                var feature=features.FirstOrDefault(f=>f.Name=="SWFORGE_"+tags[i]);
                RequireDimension(feature!=null,"feature "+tags[i]);
                DimensionProfile(feature,kinds[i]);
            }
            RequireDimension(md.ForceRebuild3(false),"rebuild");
            foreach(object item in (object[])md.FeatureManager.GetFeatures(false)) {
                var feature=(IFeature)item;
                bool warning;
                RequireDimension(feature.GetErrorCode2(out warning)==0,feature.Name+" has a rebuild error");
            }
            var after=new List<double[]>(DimensionBodySnapshot());
            RequireDimension(before.Length==after.Count,"body count changed");
            foreach(var body in before) {
                int match=after.FindIndex(candidate=>body.Zip(candidate,(a,b)=>Math.Abs(a-b)).Max()<.001);
                RequireDimension(match>=0,"nominal body volume or envelope changed");
                after.RemoveAt(match);
            }
        } finally {
            application.SetUserPreferenceToggle(input,oldInput);
            application.SetUserPreferenceToggle(overDefinitionPrompt,oldPrompt);
        }
    }
"""
