# 坑清单（本机实测，建模前必读）

每一条都是在这台机器上真实撞过、并已定位根因的。

---

## ① 零参 COM 方法在后期绑定下退化成**属性**

`win32com.client.Dispatch` 是后期绑定，SolidWorks 里所有零参方法取回来是值，
**加括号会报 `'str' object is not callable` 或 `TypeError`**。

```python
# ❌ 错
sw.RevisionNumber()
md.GetDocuments()
feat.GetTypeName2()
sw.EditRebuild3()

# ✅ 对
sw.RevisionNumber
md.GetDocuments
feat.GetTypeName2
md.EditRebuild3
```

**保险写法**（不知道是方法还是属性时）：

```python
def val(obj, name, *args):
    a = getattr(obj, name)
    if callable(a) and not hasattr(a, "_oleobj_"):
        return a(*args) if args else a()
    return a
```

---

## ② 隐藏实例建不了草图

`Dispatch` 冷启动出来的实例 `Visible == False`，
此时调 `SketchManager.InsertSketch` 抛：

```
COMException (0x80010105) RPC_E_SERVERFAULT
```

**修复**：

```python
sw = get_session().sw()
sw.Visible = True        # 必须
import time; time.sleep(2)
```

- 能手动启动 SW 就手动启动，再 `Dispatch` 附加。
- `GetActiveObject` 不要用（SW 不注册 ROT）。

---

## ③ 文档数上限 8

```python
# 报错
ERROR System.Exception: SW 文档数量达到上限，未创建新文档
SWFORGE_DOCUMENTS before=23 limit=8
```

**修复**：建之前清场。

```python
for d in (sw.GetDocuments or []):
    try:
        sw.CloseDoc(d.GetPathName)
    except Exception:
        sw.CloseDoc(d.GetTitle)      # GetPathName 也可能失败
```

---

## ④ 实例反复 kill 后 COM 会断

```
COMException (0x80010108) RPC_E_DISCONNECTED
The object invoked has disconnected from its clients.
   at SketchClass.get_ModelToSketchTransform()
```

现象：能建 5 个特征，第 6 个突然断。
**原因**：进程被反复 `Stop-Process`、或开过 20+ 文档后实例不稳。

**修复**：彻底重启

```powershell
Get-Process SLDWORKS -EA 0 | Stop-Process -Force
Start-Sleep 10
Get-Process SLDWORKS -EA 0 | Stop-Process -Force
Start-Sleep 5
Start-Process "E:\SW2025\SOLIDWORKS\SLDWORKS.exe"
# 等 MainWindowHandle != 0，再等 25 秒让 COM 服务就绪
```

---

## ⑤ `Extension.GetBox` 后期绑定不可用

```python
md.Extension.GetBox(0)
# AttributeError: <unknown>.GetBox
```

**改用实体级接口**（返回米）：

```python
bb = body.GetBodyBox()      # [xmin,ymin,zmin,xmax,ymax,zmax]
```

---

## ⑥ `SelectByID2` 在本机报类型不匹配

```python
md.Extension.SelectByID2("前视基准面","PLANE",0,0,0,False,0,None,0)
# pywintypes.com_error: (-2147352571, '类型不匹配。', None, 8)
```

**改用遍历选中**：

```python
for f in body.GetFaces():
    n = f.Normal                 # (x,y,z)
    if abs(n[2]) > 0.9:
        md.ClearSelection2(True)
        f.Select2(False, 0)      # True 也可以
```

---

## ⑦ 切除方向要按"料在哪边"判断

孔口开在顶面 `y=20`、板料在 `y<20` 一侧时：

```python
b.hole(..., direction=-1)    # ✅ 朝料里切
b.hole(..., direction= 1)    # ❌ 朝空气切
```

报错文本：

```
原生切除返回空值；孔口/方向或切除范围未与目标相交
```

**这是库的正确行为**（它拒绝了一个切不到料的切除并说明原因），不是 bug。
不要为了"让它成功"去乱改方向。

---

## ⑧ 草图约束/尺寸接口取不到

```python
sketch.GetSketchRelations()      # AttributeError
sketch.GetSketchDimensions()     # AttributeError
```

后期绑定下这两个接口都不可用。
**改草图的可行路径**：`SketchManager.CreateCornerRectangle` 重画 profile，
或直接**按结构重新建模**（更可控，见 `structure.md`）。

---

## ⑨ 临时文件别用通配符清

```powershell
Remove-Item *.png          # ❌ 会连刚生成的成果一起删掉
```

要排除目标文件，或清之前先列清单。

---

## ⑩ 冷启动失败：CO_E_SERVER_EXEC_FAILURE

```
COMException (0x80080005) CO_E_SERVER_EXEC_FAILURE
```

`Dispatch("SldWorks.Application")` 走的是 COM 自动激活，由 SCM 去拉起
`SLDWORKS.exe`。这条路会被挡住：

- 进程创建被沙箱 / 安全软件拦截
- 以不同完整性级别运行
- 安装路径改了但注册项没更新

**不要**去改注册表，也**不要**死等。用内置的启动器：

```python
from swforge.startup import ensure_running
info = ensure_running(wait_s=180, visible=True)
if not info["ok"]:
    print(info["error"], info["hint"])
```

```bash
swforge start              # 命令行等价写法
swforge start --wait 240   # SW 冷启动慢时加长等待
```

它做的事：

1. 先用 `tasklist` 看进程（**故意不用 Dispatch 判断**，否则 Dispatch
   自己会把 SW 拉起来，就永远走不到修复路径）
2. 没在跑 → 从注册表 `LocalServer32` 读真实 exe 路径，自己 `Popen` 启动
3. 轮询等进程 + COM 就绪
4. 设为可见（`Visible=True`，否则建草图会崩）

`swforge.session.SWSession.sw()` 在 Dispatch 失败时也会自动调它，
所以正常建模流程不需要手动干预。

### 找不到 exe 时

按顺序找：`参数` → `环境变量 SWFORGE_SW_EXE` → `resources.paths`
→ `注册表 LocalServer32` → 常见安装位置。
都不行就设环境变量：

```powershell
setx SWFORGE_SW_EXE "E:\SW2025\SOLIDWORKS\SLDWORKS.exe"
```

---

## ⑪ 临时目录清理失败

沙箱下 `TemporaryDirectory` 退出时可能删不掉（`scandir/chmod` 被拒），
报 `PermissionError` 并把整个建模结果带崩。

库内已对三处加 `ignore_cleanup_errors=True`：
`modeling.py` / `native_bridge.py` / `mate_faces.py`。

**清理只是收尾，不该让建模结论作废。**
