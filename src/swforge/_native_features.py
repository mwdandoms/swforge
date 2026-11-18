"""Native editable finishing features for PartBuilder."""
import json
import math
import re


def axis_index(axis):
    if axis not in ("x", "y", "z"):
        raise ValueError("axis must be x, y or z")
    return "xyz".index(axis)


def vector(values, count, label):
    try:
        if isinstance(values, (str, bytes)):
            raise ValueError()
        values = tuple(values)
        if len(values) != count or any(isinstance(v, (bool, str, bytes)) for v in values):
            raise ValueError()
        values = tuple(float(v) for v in values)
        if not all(math.isfinite(v) for v in values):
            raise ValueError()
        return values
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " requires " + str(count) + " finite numbers") from exc


def scalar(value, label, positive=False):
    v = vector((value,), 1, label)[0]
    if positive and v <= 0:
        raise ValueError(label + " must be positive")
    return v


def flag(value):
    if type(value) is not bool:
        raise ValueError("reverse must be boolean")
    return int(value)


def instances(count):
    if type(count) is not int or not 2 <= count <= 200:
        raise ValueError("count must be an integer from 2 to 200, including seed")
    return count


class NativePartFeatures:
    def _native_add(self, kind, tag, values, seed=None):
        tag = str(tag)
        if not tag.strip() or tag in self._tags:
            raise ValueError("tag must be nonempty and unique: " + tag)
        if seed is not None and seed not in ({r[1] for r in self._shapes} | {r[1] for r in self._cuts}):
            raise ValueError("seed/target must be an existing shape or cut tag: " + str(seed))
        self._tags.add(tag)
        self._native_ops.append((kind, tag, values))
        return self

    def linear_pattern(self, tag, seed, *, axis, count, spacing, reverse=False):
        """Repeat one native feature along a datum axis; spacing in mm."""
        axis_index(axis)
        return self._native_add("LinearPattern", tag, (seed, axis, instances(count),
                                scalar(spacing, "spacing", True), flag(reverse)), seed)

    def circular_pattern(self, tag, seed, *, axis, count, angle=360, reverse=False):
        """Repeat one native feature about an origin axis over a total angle in degrees."""
        axis_index(axis)
        angle = scalar(angle, "angle", True)
        if angle > 360:
            raise ValueError("angle cannot exceed 360 degrees")
        return self._native_add("CircularPattern", tag, (seed, axis, instances(count),
                                angle, flag(reverse)), seed)

    def mirror(self, tag, seed, *, plane):
        """Mirror one native feature about XY, XZ or YZ at the origin."""
        if plane not in ("xy", "xz", "yz"):
            raise ValueError("plane must be xy, xz or yz")
        return self._native_add("MirrorFeature", tag, (seed, {"xy": "z", "xz": "y", "yz": "x"}[plane]), seed)

    def shell(self, tag, target, *, thickness, open_side):
        """Inward shell opening the unique extreme planar face at ±X/Y/Z."""
        if open_side not in ("+x", "-x", "+y", "-y", "+z", "-z"):
            raise ValueError("open_side must be +x/-x/+y/-y/+z/-z")
        return self._native_add("ShellFeature", tag, (target, open_side,
                                scalar(thickness, "thickness", True)), target)

    def rib(self, tag, *, axis, start, end, thickness, reverse_material=False):
        """Native symmetric rib from an open straight line on an axis-normal plane."""
        i = axis_index(axis)
        start, end = vector(start, 3, "start"), vector(end, 3, "end")
        if abs(start[i] - end[i]) > 1e-8 or start == end:
            raise ValueError("rib endpoints must be distinct and in the same axis-normal plane")
        return self._native_add("RibFeature", tag, (axis,) + start + end +
                                (scalar(thickness, "thickness", True), flag(reverse_material)))

    def loft(self, tag, *, axis, sections, color="silver"):
        """Native solid loft through 2–20 parallel circular sections (x,y,z,radius), mm."""
        i = axis_index(axis)
        sections = [vector(s, 4, "section") for s in sections]
        if not 2 <= len(sections) <= 20 or any(s[3] <= 0 for s in sections):
            raise ValueError("loft requires 2–20 circular sections with positive radii")
        if any(b[i] - a[i] <= 1e-6 for a, b in zip(sections, sections[1:])):
            raise ValueError("loft section offsets must be strictly increasing along axis")
        self._add(tag, "LoftFeature", (axis, tuple(n for s in sections for n in s)), color)
        return self

    def cosmetic_thread(self, tag, seed, *, center, edge_diameter, diameter, depth, note=""):
        """Native blind thread annotation attached to a circle, without cutting the solid."""
        if not isinstance(note, str) or any(ord(c) < 32 for c in note):
            raise ValueError("note must be single-line text")
        edge = scalar(edge_diameter, "edge_diameter", True)
        dia = scalar(diameter, "diameter", True)
        if abs(edge - dia) < 1e-6:
            raise ValueError("thread diameter must differ from start edge diameter")
        return self._native_add("CosmeticThreadFeature", tag, (seed,) + vector(center, 3, "center") +
                                (edge, dia, scalar(depth, "depth", True), note), seed)


def evidence(log):
    return [{"operation": m[1], "tag": json.loads(m[2]), "type": m[3],
             "bodies_before": int(m[4]), "bodies_after": int(m[5]),
             "volume_before_mm3": float(m[6]), "volume_after_mm3": float(m[7])}
            for m in re.finditer(r'SWFORGE_NATIVE (\w+) tag=("(?:[^"\\]|\\.)*") type=(\w+) '
                                 r'bodies=(\d+),(\d+) volume_mm3=([0-9.eE+-]+),([0-9.eE+-]+)', log)]


CS = r"""
    static List<IFeature> verifiedNative=new List<IFeature>();

    static double[] State() {
        object[] bodies=(object[])((IPartDoc)md).GetBodies2(0,false) ?? new object[0];
        double volume=0;
        foreach(object o in bodies) {
            double[] p=(double[])((IBody2)o).GetMassProperties(1);
            if(p==null || p.Length<4 || !(p[3]>0) || Double.IsInfinity(p[3]))
                throw new Exception("Cannot read solid volume");
            volume+=p[3]*1e9;
        }
        return new double[]{bodies.Length,volume};
    }

    static void CheckNative(string tag, IFeature f) {
        if(f==null) throw new Exception(tag+": SolidWorks did not create the feature");
        bool warning;
        int code=f.GetErrorCode2(out warning);
        if(code!=0) throw new Exception(tag+": feature error "+code+" warning="+warning);
    }

    static void NativeDone(string op,string tag,IFeature f,double[] before,int delta) {
        CheckNative(tag,f);
        md.ClearSelection2(true);
        if(!md.EditRebuild3()) throw new Exception(tag+": rebuild failed");
        CheckNative(tag,f);
        double[] after=State();
        if(after[0]==0 || (delta==0 && (after[0]!=before[0] || Math.Abs(after[1]-before[1])>1e-5)) ||
           (delta>0 && !(after[1]>before[1]+1e-5)) || (delta<0 && !(after[1]<before[1]-1e-5)))
            throw new Exception(tag+": unexpected solid change "+before[1]+" -> "+after[1]);
        f.Name="SWFORGE_"+tag;
        sources[tag]=f;
        verifiedNative.Add(f);
        L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
            "SWFORGE_NATIVE {0} tag=\"{1}\" type={2} bodies={3},{4} volume_mm3={5:R},{6:R}",
            op,tag.Replace("\\","\\\\").Replace("\"","\\\"").Replace("\r","\\r").Replace("\n","\\n").Replace("\t","\\t"),
            f.GetTypeName2(),before[0],after[0],before[1],after[1]));
        okN++;
    }

    static IFeature Seed(string tag) {
        IFeature f;
        if(!sources.TryGetValue(tag,out f)) throw new Exception("Missing native seed: "+tag);
        return f;
    }

    static void SelectFeature(IFeature f,bool append,int mark) {
        if(!f.Select2(append,mark)) throw new Exception("Cannot select "+f.Name+" mark="+mark);
    }

    static void SelectEntity(IEntity entity,bool append,int mark) {
        ISelectionMgr mgr=(ISelectionMgr)md.SelectionManager;
        SelectData data=(SelectData)mgr.CreateSelectData();
        data.Mark=mark;
        if(!entity.Select4(append,data)) throw new Exception("Cannot select topology reference mark="+mark);
    }

    static IFeature LastOfType(string kind) {
        IFeature last=null;
        for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())
            if(f.GetTypeName2()==kind)last=f;
        return last;
    }

    static Dictionary<string,IFeature> axes=new Dictionary<string,IFeature>();
    static IFeature AxisFeature(string axis) {
        if(axes.ContainsKey(axis))return axes[axis];
        IFeature previous=LastOfType("RefAxis");
        md.ClearSelection2(true);
        SelectFeature(Datum(axis=="x"?"y":"x"),false,0);
        SelectFeature(Datum(axis=="z"?"y":"z"),true,0);
        if(!md.InsertAxis2(true)) throw new Exception("Cannot create "+axis+" datum axis");
        IFeature f=LastOfType("RefAxis");
        if(f==null || Object.ReferenceEquals(previous,f)) throw new Exception("Datum axis missing");
        f.Name="SWFORGE_direction_"+axis;
        axes[axis]=f;
        return f;
    }

    static bool PatternFlip(IFeature direction,string axis,bool reverse) {
        IRefAxis datum=(IRefAxis)direction.GetSpecificFeature2();
        double[] p=(double[])datum.GetRefAxisParams();
        int i=AxisIndex(axis);
        if(p==null || p.Length!=6 || Math.Abs(p[i+3]-p[i])<1e-9)
            throw new Exception("Cannot read signed "+axis+" datum direction");
        return (p[i+3]<p[i]) ^ reverse;
    }

    static void LinearPattern(string tag,string seed,string axis,double n,double pitch,double reverse) {
        double[] before=State();
        IFeature direction=AxisFeature(axis);
        md.ClearSelection2(true);
        SelectFeature(direction,false,1);
        SelectFeature(Seed(seed),true,4);
        bool flip=PatternFlip(direction,axis,reverse>0);
        IFeature f=(IFeature)md.FeatureManager.FeatureLinearPattern4((int)n,pitch*MM,1,0,
            flip,false,"","",false,false,false,false,false,false,false,false,false,false,0,0);
        CheckNative(tag,f);
        ILinearPatternFeatureData def=(ILinearPatternFeatureData)f.GetDefinition();
        if(def.D1TotalInstances!=(int)n || def.D1ReverseDirection!=flip || Math.Abs(def.D1Spacing-pitch*MM)>1e-8)
            throw new Exception(tag+": pattern parameter readback mismatch");
        NativeDone("linear_pattern",tag,f,before,State()[1]>before[1]?1:-1);
    }

    static void CircularPattern(string tag,string seed,string axis,double n,double angle,double reverse) {
        double[] before=State();
        IFeature direction=AxisFeature(axis);
        md.ClearSelection2(true);
        SelectFeature(direction,false,1);
        SelectFeature(Seed(seed),true,4);
        bool flip=PatternFlip(direction,axis,reverse>0);
        IFeature f=(IFeature)md.FeatureManager.FeatureCircularPattern5((int)n,angle*Math.PI/180,
            flip,"",false,true,false,false,false,false,1,0,"",false);
        CheckNative(tag,f);
        ICircularPatternFeatureData def=(ICircularPatternFeatureData)f.GetDefinition();
        if(def.TotalInstances!=(int)n || !def.EqualSpacing || def.ReverseDirection!=flip || Math.Abs(def.Spacing-angle*Math.PI/180)>1e-8)
            throw new Exception(tag+": circular pattern parameter readback mismatch, spacing="+def.Spacing);
        NativeDone("circular_pattern",tag,f,before,State()[1]>before[1]?1:-1);
    }

    static void MirrorFeature(string tag,string seed,string axis) {
        double[] before=State();
        md.ClearSelection2(true);
        SelectFeature(Seed(seed),false,1);
        SelectFeature(Datum(axis),true,2);
        IFeature f=(IFeature)md.FeatureManager.InsertMirrorFeature2(false,false,false,false,0);
        CheckNative(tag,f);
        NativeDone("mirror",tag,f,before,State()[1]>before[1]?1:-1);
    }

    static int AxisIndex(string axis) { return axis=="x"?0:axis=="y"?1:2; }

    static void ShellFeature(string tag,string target,string side,double thickness) {
        double[] before=State();
        if(before[0]!=1) throw new Exception(tag+": shell needs a single solid body");
        IBody2 body=BodyOf(Seed(target));
        int axis=AxisIndex(side.Substring(1)), sign=side[0]=='+'?1:-1;
        double px=0,py=0,pz=0;
        if(!body.GetExtremePoint(axis==0?sign:0,axis==1?sign:0,axis==2?sign:0,out px,out py,out pz))
            throw new Exception(tag+": cannot find body extreme");
        double extreme=new double[]{px,py,pz}[axis];
        var found=new List<IFace2>();
        foreach(object o in (object[])body.GetFaces()) {
            IFace2 face=(IFace2)o;
            if(!((ISurface)face.GetSurface()).IsPlane()) continue;
            double[] normal=(double[])face.Normal, box=(double[])face.GetBox();
            if(normal[axis]*sign>0.999999 && Math.Abs(box[axis]-extreme)<1e-7 &&
               Math.Abs(box[axis+3]-extreme)<1e-7) found.Add(face);
        }
        if(found.Count!=1) throw new Exception(tag+": shell opening face missing or ambiguous ("+found.Count+")");
        md.ClearSelection2(true);
        // SW2025 SP5 returns null from CreateDefinition(swFmShell).
        // Select the exact topology object and read the definition from the created feature.
        IFeature previous=LastOfType("Shell");
        SelectEntity((IEntity)found[0],false,1);
        md.InsertFeatureShell(thickness*MM,false);
        IFeature f=LastOfType("Shell");
        if(f==null || Object.ReferenceEquals(previous,f)) throw new Exception(tag+": shell missing");
        CheckNative(tag,f);
        IShellFeatureData got=(IShellFeatureData)f.GetDefinition();
        if(got.FacesRemovedCount!=1 || Math.Abs(got.Thickness-thickness*MM)>1e-8)
            throw new Exception(tag+": shell readback mismatch");
        NativeDone("shell",tag,f,before,-1);
    }

    static ISketch BeginNativeProfile(string axis,double offset) {
        IRefPlane plane=(IRefPlane)Datum(axis).GetSpecificFeature2();
        IMathVector normal=(IMathVector)math.CreateVector(new double[]{0,0,1});
        normal=(IMathVector)normal.MultiplyTransform(plane.Transform);
        double[] v=(double[])normal.ArrayData;
        return Begin(axis,offset*(v[AxisIndex(axis)]<0?-1:1));
    }

    static void RibFeature(string tag,string axis,double x,double y,double z,
            double xx,double yy,double zz,double thickness,double reverse) {
        double[] before=State();
        if(before[0]!=1) throw new Exception(tag+": rib needs a single solid body");
        ISketch sketch=BeginNativeProfile(axis,new double[]{x,y,z}[AxisIndex(axis)]);
        double[] a=Local(sketch,x,y,z),b=Local(sketch,xx,yy,zz);
        if(md.SketchManager.CreateLine(a[0],a[1],0,b[0],b[1],0)==null)
            throw new Exception(tag+": cannot create rib profile");
        IFeature profile=End(sketch);
        profile.Name="SWFORGE_"+tag+"_profile";
        md.ClearSelection2(true);
        SelectFeature(profile,false,0);
        IFeature previous=LastOfType("Rib");
        md.FeatureManager.InsertRib(true,false,thickness*MM,0,reverse>0,false,false,0,false,false);
        IFeature f=LastOfType("Rib");
        if(f==null || Object.ReferenceEquals(previous,f)) throw new Exception(tag+": rib missing");
        IRibFeatureData2 def=(IRibFeatureData2)f.GetDefinition();
        if(!def.IsTwoSided || Math.Abs(def.Thickness-thickness*MM)>1e-8)
            throw new Exception(tag+": rib thickness readback mismatch");
        NativeDone("rib",tag,f,before,1);
    }

    static void LoftFeature(string tag,string axis,double[] points,double[] rgb) {
        bool add=md.SketchManager.AddToDB;
        md.SketchManager.AddToDB=false;
        try {
            double[] before=State();
            var profiles=new List<IFeature>();
            for(int i=0;i<points.Length;i+=4) {
                ISketch sketch=BeginNativeProfile(axis,points[i+AxisIndex(axis)]);
                double[] p=Local(sketch,points[i],points[i+1],points[i+2]);
                if(md.SketchManager.CreateCircleByRadius(p[0],p[1],0,points[i+3]*MM)==null)
                    throw new Exception(tag+": cannot create loft section");
                IFeature profile=End(sketch);
                profile.Name="SWFORGE_"+tag+"_section_"+(1+i/4);
                profiles.Add(profile);
            }
            md.ClearSelection2(true);
            for(int i=0;i<profiles.Count;i++) SelectFeature(profiles[i],i>0,1);
            IFeature f=(IFeature)md.FeatureManager.InsertProtrusionBlend2(false,true,false,1,0,0,1,1,
                true,true,false,0,0,0,MERGE,false,true,0);
            CheckNative(tag,f);
            ILoftFeatureData def=(ILoftFeatureData)f.GetDefinition();
            if(def==null) throw new Exception(tag+": no native loft data");
            NativeDone("loft",tag,f,before,1);
            BodyOf(f).Name=tag;
            colors[tag]=rgb;
        } finally { md.SketchManager.AddToDB=add; }
    }

    static void CosmeticThreadFeature(string tag,string seed,double x,double y,double z,
            double edgeDiameter,double diameter,double depth,string note) {
        double[] before=State();
        IBody2 body=BodyOf(Seed(seed));
        var edges=new List<IEdge>();
        foreach(object o in (object[])body.GetEdges()) {
            IEdge edge=(IEdge)o;
            ICurve curve=(ICurve)edge.GetCurve();
            if(curve==null || !curve.IsCircle()) continue;
            double[] p=(double[])curve.CircleParams;
            if(p!=null && p.Length>=7 && Math.Abs(p[0]-x*MM)<1e-6 &&
                Math.Abs(p[1]-y*MM)<1e-6 && Math.Abs(p[2]-z*MM)<1e-6 &&
                Math.Abs(2*p[6]-edgeDiameter*MM)<1e-6) edges.Add(edge);
        }
        if(edges.Count!=1) throw new Exception(tag+": circular start edge missing or ambiguous ("+edges.Count+")");
        md.ClearSelection2(true);
        SelectEntity((IEntity)edges[0],false,0);
        IFeature f=(IFeature)md.FeatureManager.InsertCosmeticThread3(-2,"","",diameter*MM,0,depth*MM,note);
        CheckNative(tag,f);
        ICosmeticThreadFeatureData def=(ICosmeticThreadFeatureData)f.GetDefinition();
        if(def==null || Math.Abs(def.Diameter-diameter*MM)>1e-8 ||
            Math.Abs(def.BlindDepth-depth*MM)>1e-8 || def.EndCondition!=0)
            throw new Exception(tag+": thread diameter or depth readback mismatch");
        NativeDone("cosmetic_thread",tag,f,before,0);
    }
"""
