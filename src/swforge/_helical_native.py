"""C# feature routines injected into the existing PartBuilder native bridge."""
CS = r"""
    // Community deliverables contain copied B-Rep bodies, not a hidden native tree.
    // Only documents created by this build are ever closed here.
    static void FlattenCommunityGeometry(ISldWorks sw,string template) {
        IModelDoc2 source=md;
        object[] originals=(object[])((IPartDoc)source).GetBodies2(0,false);
        if(originals==null||originals.Length==0)throw new Exception("No geometry to deliver");
        var copies=new List<IBody2>();var names=new List<string>();
        var volumes=new List<double>();var spans=new List<double[]>();
        foreach(IBody2 body in originals) {
            copies.Add((IBody2)body.Copy2(false));names.Add(body.Name);
            volumes.Add(BodyVolumeMm3(body));spans.Add(ExactBounds(body));
            if(copies[copies.Count-1]==null)throw new Exception("Body copy failed");
        }
        IModelDoc2 output=null;
        try {
            output=(IModelDoc2)sw.NewDocument(template,0,0,0);
            if(output==null)throw new Exception("Cannot create Community geometry document");
            md=output;
            sources.Clear();verifiedNative.Clear();
            for(int i=0;i<copies.Count;i++) {
                IFeature imported=(IFeature)((IPartDoc)output).CreateFeatureFromBody3(copies[i],false,0);
                if(imported==null)throw new Exception("Imported solid creation failed");
                imported.Name="SWFORGE_geometry_"+names[i];
                IBody2 body=BodyOf(imported);body.Name=names[i];
                NearHelical("Delivered volume",BodyVolumeMm3(body),volumes[i],1e-8,.00001);
                double[] span=ExactBounds(body);
                for(int axis=0;axis<3;axis++)NearHelical("Delivered span",span[axis],spans[i][axis],1e-8,.00001);
                CheckNative(imported.Name,imported);
            }
            if(!output.EditRebuild3())throw new Exception("Geometry document rebuild failed");
            object[] delivered=(object[])((IPartDoc)output).GetBodies2(0,false);
            if(delivered==null||delivered.Length!=originals.Length)throw new Exception("Delivered body count mismatch");
            for(IFeature f=(IFeature)output.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature()) {
                string type=f.GetTypeName2();
                if(type=="Helix"||type=="Sweep"||type=="SweepRefSurface"||type=="Thicken"||
                   type=="ProfileFeature"||type=="3DProfileFeature")
                    throw new Exception("Native construction history entered geometry deliverable");
                if(f.GetFirstDisplayDimension()!=null)throw new Exception("Unexpected driving dimension in geometry deliverable");
            }
            L("SWFORGE_COMMUNITY geometry_only=True native_history=False bodies="+delivered.Length);
        } catch {
            if(output!=null)try{sw.CloseDoc(output.GetTitle());}catch{}
            md=source;throw;
        }
        sw.CloseDoc(source.GetTitle());
    }
    static string HelicalKey(string tag) {
        return Convert.ToBase64String(Encoding.UTF8.GetBytes(tag));
    }

    static double BodyVolumeMm3(IBody2 body) {
        double[] mass=(double[])body.GetMassProperties(1.0);
        if(mass==null || mass.Length<4 || !(mass[3]>0) || Double.IsInfinity(mass[3]))
            throw new Exception("Cannot read the helical solid volume");
        return mass[3]*1e9;
    }

    static void NearHelical(string property,double actual,double expected,double relative,double absolute) {
        if(Double.IsNaN(actual) || Double.IsInfinity(actual) ||
           Math.Abs(actual-expected)>Math.Max(absolute,Math.Abs(expected)*relative))
            throw new Exception(property+" mismatch: expected "+expected+", got "+actual);
    }

    static void HelixSpring(string tag,double meanDia,double wireDia,double height,double turns,bool clockwise,double[] rgb) {
        IFeature previous=LastOfType("Helix");
        ISketch sketch=Begin("y",0);
        double[] p=Local(sketch,0,0,0);
        if(md.SketchManager.CreateCircleByRadius(p[0],p[1],0,meanDia*MM/2)==null)
            throw new Exception(tag+": cannot create helix base circle");
        IFeature circle=End(sketch);
        circle.Name="SWFORGE_"+tag+"_circle";

        double pitch=height/turns;
        md.InsertHelix(false,clockwise,false,false,1,height*MM,pitch*MM,turns,0,0);
        IFeature helix=LastOfType("Helix");
        if(helix==null || Object.ReferenceEquals(helix,previous))
            throw new Exception(tag+": a new helix was not found");
        CheckNative(tag,helix);
        helix.Name="SWFORGE_"+tag+"_helix";
        IHelixFeatureData helixData=(IHelixFeatureData)helix.GetDefinition();
        if(helixData==null || helixData.Clockwise!=clockwise || helixData.VariablePitch || helixData.Taper)
            throw new Exception(tag+": helix handedness or type readback mismatch");
        NearHelical("Helix rise",helixData.Height*1000,height,0,1e-5);
        NearHelical("Helix pitch",helixData.Pitch*1000,pitch,0,1e-5);
        NearHelical("Helix turns",helixData.Revolution,turns,0,1e-7);

        md.ClearSelection2(true);
        SelectFeature(helix,false,4);
        IFeature swept=(IFeature)md.FeatureManager.InsertProtrusionSwept4(
            false,false,0,false,false,0,0,false,0,0,0,0,true,false,true,0,false,true,wireDia*MM,0);
        CheckNative(tag,swept);
        ISweepFeatureData sweep=(ISweepFeatureData)swept.GetDefinition();
        if(sweep==null || !sweep.CircularProfile)
            throw new Exception(tag+": no native circular sweep profile");
        NearHelical("Sweep wire diameter",sweep.CircularProfileDiameter*1000,wireDia,0,1e-5);

        IBody2 body=BodyOf(swept);
        double volume=BodyVolumeMm3(body);
        double[] span=ExactBounds(body);
        double circumference=Math.PI*meanDia;
        double length=Math.Sqrt(Math.Pow(circumference*turns,2)+height*height);
        double axial=height+wireDia*circumference/Math.Sqrt(circumference*circumference+pitch*pitch);
        NearHelical("Spring volume",volume,Math.PI*wireDia*wireDia/4*length,.005,0);
        NearHelical("Spring X span",span[0],meanDia+wireDia,.002,.03);
        NearHelical("Spring Y span",span[1],axial,.002,.03);
        NearHelical("Spring Z span",span[2],meanDia+wireDia,.002,.03);

        md.ClearSelection2(true);
        Register(tag,swept,rgb);
        verifiedNative.Add(helix);
        verifiedNative.Add(swept);
        L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
            "SWFORGE_SPRING {0} {1:R} {2:R} {3:R} {4:R} {5:R} {6:R} {7:R} {8}",
            HelicalKey(tag),volume,span[0],span[1],span[2],helixData.Pitch*1000,
            helixData.Height*1000,helixData.Revolution,clockwise?1:0));
    }

    static void AugerFlight(string tag,double inner,double outer,double pitch,double turns,double thickness,
            double hand,double areaExpected,double volumeExpected,double radialExpected,double axialExpected,double[] rgb) {
        double[] before=State();
        bool add=md.SketchManager.AddToDB;
        try {
            double height=pitch*turns, angle=hand*turns*2*Math.PI;
            ISketch section=Begin("y",0);
            double[] a=Local(section,inner/2,0,0), b=Local(section,outer/2,0,0);
            if(md.SketchManager.CreateLine(a[0],a[1],0,b[0],b[1],0)==null)
                throw new Exception(tag+": cannot create radial profile");
            IFeature profile=End(section);
            profile.Name="SWFORGE_"+tag+"_radial_profile";
            ISketch pathSketch=Begin("z",0);
            a=Local(pathSketch,0,0,0); b=Local(pathSketch,0,height,0);
            if(md.SketchManager.CreateLine(a[0],a[1],0,b[0],b[1],0)==null)
                throw new Exception(tag+": cannot create axial path");
            IFeature path=End(pathSketch);
            path.Name="SWFORGE_"+tag+"_axial_path";

            md.SketchManager.AddToDB=false;
            md.ClearSelection2(true);
            SelectFeature(profile,false,1);
            SelectFeature(path,true,4);
            int twist=(int)swTwistControlType_e.swTwistControlConstantTwistAlongPath;
            IFeature surface=(IFeature)md.FeatureManager.InsertSweepSurface3(
                false,twist,false,false,0,0,0,false,true,angle,false,false,0,0);
            CheckNative(tag+" helicoid",surface);
            surface.Name="SWFORGE_"+tag+"_helicoid";
            ISweepFeatureData def=(ISweepFeatureData)surface.GetDefinition();
            if(def==null || def.TwistControlType!=twist)
                throw new Exception(tag+": surface twist definition mismatch");
            NearHelical("Auger twist radians",def.GetTwistAngle(),angle,0,1e-7);

            object[] faces=(object[])surface.GetFaces();
            if(faces==null || faces.Length==0) throw new Exception(tag+": no swept surface faces");
            double area=0, phaseError=Double.PositiveInfinity;
            double yy=pitch*MM/4, zz=-hand*(inner+outer)*MM/4;
            foreach(IFace2 face in faces) {
                area+=face.GetArea()*1e6;
                double[] p=(double[])face.GetClosestPointOn(0,yy,zz);
                if(p!=null && p.Length>=3) {
                    double distance=Math.Sqrt(p[0]*p[0]+Math.Pow(p[1]-yy,2)+Math.Pow(p[2]-zz,2))*1000;
                    phaseError=Math.Min(phaseError,distance);
                }
            }
            NearHelical("Helicoid area",area,areaExpected,.005,0);
            NearHelical("Helicoid quarter-turn point",phaseError,0,0,.05);

            md.ClearSelection2(true);
            SelectFeature(surface,false,1);
            int both=(int)swThickenDirection_e.swThickenDirection_Both;
            IFeature solid=(IFeature)md.FeatureManager.FeatureBossThicken(thickness*MM/2,both,0,false,false,false,true);
            CheckNative(tag+" thicken",solid);
            IThickenFeatureData thick=(IThickenFeatureData)solid.GetDefinition();
            if(thick==null || thick.ThicknessSide!=both)
                throw new Exception(tag+": symmetric thickness readback mismatch");
            NearHelical("Auger total normal thickness",2*thick.Thickness*1000,thickness,0,1e-5);

            IBody2 body=BodyOf(solid);
            double volume=BodyVolumeMm3(body);
            double[] span=ExactBounds(body);
            if(State()[0]!=before[0]+1) throw new Exception(tag+": expected exactly one new solid");
            NearHelical("Auger solid volume",volume,volumeExpected,.01,0);
            NearHelical("Auger X span",span[0],radialExpected,.003,.03);
            NearHelical("Auger Y span",span[1],axialExpected,.003,.03);
            NearHelical("Auger Z span",span[2],radialExpected,.003,.03);
            md.ClearSelection2(true);
            Register(tag,solid,rgb);
            verifiedNative.Add(surface);
            verifiedNative.Add(solid);
            L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
                "SWFORGE_AUGER {0} {1:R} {2:R} {3:R} {4:R} {5:R} {6:R} {7:R} {8:R}",
                HelicalKey(tag),volume,span[0],span[1],span[2],area,phaseError,def.GetTwistAngle(),2*thick.Thickness*1000));
        } finally { md.SketchManager.AddToDB=add; }
    }
"""
