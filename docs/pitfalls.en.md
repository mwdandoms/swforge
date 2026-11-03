[中文](pitfalls.md) | **English**

# Pitfalls

This document is the most valuable part of the project — every item was actually hit,
and most were only understood after **independent readback**.

---

## 1. `errStatus == 0` does not always mean success

The last out-parameter of `IAssemblyDoc.AddMate5` is `swAddMateError_e`:

```
swAddMateError_ErrorUknown         = 0
swAddMateError_NoError             = 1     ← success is 1, not 0
swAddMateError_IncorrectSelections = 4
```

**Lesson**: don't assume "0 means success". Look up the enum, don't guess.

---

## 2. `IBody2.Operations2` only accepts API temporary bodies

Boolean-intersecting two document bodies directly:

```
Operations2(SWBODYINTERSECT=15901, toolBody, out err)
→ returns (None, 1)
```

In `swBodyOperationError_e`, **1 is `swBodyOperationNonApiBody`**.

**Fix**:

```python
ta = body_a.Copy2(False)      # IsTemporaryBody() → True
tb = body_b.Copy2(False)
res = ta.Operations2(15901, tb, 0)   # pass a plain int for the out-param
arr, code = res                       # returns (result, errorcode)
```

**Another trap**: passing `VARIANT(VT_BYREF|VT_I4)` for the out-param raises
`TypeError: int() argument must be ... not 'VARIANT'`. Pass a **plain int**.

---

## 3. Late binding cannot reach some face / edge / vertex methods

| Call | pywin32 late binding | C# early binding |
|---|---|---|
| `IFace2.GetSurface()` | ❌ member not found | ✅ |
| `IEntity.Select4()` | ❌ type mismatch | ✅ |
| `IVertex.GetPoint()` | ❌ TypeError | ✅ |
| `IComponent2.GetBodies2(0)` | ⚠️ wrong parameter count | ✅ |

**Conclusion**: anything touching faces, edges, vertices or components must go through
generated C#.

Note: `IFace2` does not inherit `IEntity` in the interop, but the underlying `Face2`
COM object supports the `IEntity` QI, so in C# you write `(IEntity)(object)face`.

---

## 4. SolidWorks does not register in the ROT

`Marshal.GetActiveObject("SldWorks.Application")` only succeeds when SolidWorks was
started **interactively**. When it is launched in the background through COM `Dispatch`:

```
COMException 0x800401E3 (MK_E_UNAVAILABLE)
```

**Fix**: two-level fallback

```csharp
try { sw = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application"); }
catch { sw = (ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application")); }
```

**And do a real round-trip probe** (`RevisionNumber()` + `GetDocumentCount()`),
because `Activator.CreateInstance` sometimes returns an **empty shell proxy** —
checking only for non-null gives a false positive.

---

## 5. The material library must live in a directory SolidWorks scans

The same `.sldmat` file:

| Location | Result |
|---|---|
| `E:\...\lang\chinese-simplified\sldmaterials\` | ✅ works |
| `%LOCALAPPDATA%\swforge\` | ❌ fails silently, density falls back to 1000 |
| `C:\ProgramData\SOLIDWORKS\SOLIDWORKS <year>\自定义材料\` | ✅ works |

Also, SolidWorks' bundled Chinese library has **no GB grades** (no Q235 / 45 / 40Cr),
so you have to generate them. Generate by **cloning material nodes from the native
library** and changing only the name and DENS/EX/NUXY — hand-written XML is rejected
as an invalid library.

---

## 6. Convert units once, at the boundary

`IAssemblyDoc.AddComponent5(path, ..., X, Y, Z)` expects **metres**, while this project's
convention is **millimetres**. Without conversion, a part lands **60 metres away** — and
that also silently invalidated the "5 mm overlap" interference test, which could never
detect an overlap.

**Convention**: millimetres everywhere outside COM; divide by 1000 going in, multiply
coming out.

---

## 7. `_value()` calling a method that requires arguments

The generic wrapper `_value(obj, name)` calls `value()` with no arguments. For COM methods
that need arguments (like `GetUserPreferenceInteger(47, 0)`) this raises
"the parameter is not optional".

**Fix**: call parameterized methods explicitly, don't route them through the generic wrapper.

---

## 8. `except: continue` disguises "could not read" as "does not exist"

An early `_view_list()` used `md.GetViews`, which returns a native `PyIDispatch`;
attribute access threw, and `except: continue` swallowed it — so the counting function
**always returned 0 views** while callers saw nothing wrong.

**Fix**: switch to the `GetFirstView()` linked list; and anywhere you catch and continue,
leave a visible failure signal.

---

## 9. The drawing template decides units and frame

`E:\...\data\templates\GB.drwdot` is an **English template**: inches, no GB sheet format.
`C:\ProgramData\...\templates\gb_a3.drwdot` is the Chinese one: millimetres,
`a3 - gb.slddrt`.

Using the wrong template shows up as 100 mm rendered as `3.94` (inches) and a sheet
with no border or title block.

---

## 10. `InsertModelAnnotations4` does not give overall dimensions

It inserts **model driving dimensions**. A part made of "one base plate + four plates
welded into a tube" only has a dozen of them, and SolidWorks **deduplicates them across
views** (which is why a top view often legitimately shows 0 dimensions). Measured cap:
18. And they are frequently vertical-only.

Overall dimensions must be added explicitly: take
`IView.GetVisibleEntities2(null, swViewEntityType_Vertex=2)`, find the extreme vertices
by model coordinate, select them, then call `AddHorizontalDimension2` /
`AddVerticalDimension2`.
