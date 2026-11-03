# 「为什么 SolidWorks 的 GetActiveObject 会失败」

> 这是 swforge 项目里最值得单独写一篇的技术点。
> 踩过这个坑的人很多，但把原因查清楚的很少 —— 大多数方案是"多试几次"或者"重装"。
>
> 项目地址：https://github.com/mwdandoms/swforge

---

## 先说结论

`Marshal.GetActiveObject("SldWorks.Application")` 会失败，
**不是因为 SolidWorks 没启动，而是因为它不在 ROT 里。**

ROT = **Running Object Table**（运行对象表），Windows 的一个全局表，
记录「当前有哪些 COM 对象正在运行、可以通过名字找到」。

SolidWorks 只有在**用户交互式启动**时才会把自己的 COM 对象注册进 ROT。
如果它是由你的程序通过 COM `Dispatch` **从后台拉起来**的，
那它压根没走注册那步 —— 你再去 ROT 里找，当然找不到。

---

## 一、先把现象看清楚

### 代码

```python
import win32com.client

sw = win32com.client.GetActiveObject("SldWorks.Application")
```

### 两种结果

**情况 A：你先手动打开了 SolidWorks，再跑这段代码**

```python
>>> sw = win32com.client.GetActiveObject("SldWorks.Application")
>>> sw.RevisionNumber()
'33.5.0'
```

正常。

**情况 B：SolidWorks 是从后台被拉起来的，或者刚开机还没打开**

```python
>>> sw = win32com.client.GetActiveObject("SldWorks.Application")
Traceback (most recent call last):
pywintypes.com_error: (-2147221005, '无效的类字符串', None, None)
```

或者（另一种表现）：

```python
pywintypes.com_error: (-2147221021, '操作无法使用', None, None)     # MK_E_UNAVAILABLE
```

### 错误码对照

| HRESULT | 十进制 | 符号 | 含义 |
|---|---|---|---|
| `0x800401E3` | -2147221021 | `MK_E_UNAVAILABLE` | **ROT 里没有这个对象** |
| `0x800401F3` | -2147221005 | `CO_E_CLASSSTRING` | ProgID 无效（没装 SW，或装了但没注册） |
| `0x80080005` | -2146959355 | `CO_E_SERVER_EXEC_FAILURE` | 服务器进程起不来 |

绝大多数人的情况是第一个：**`MK_E_UNAVAILABLE`**。

---

## 二、为什么 SolidWorks 不注册 ROT

### 2.1 COM 的两种启动方式

COM 组件有两条启动路径，走哪条决定了它注册不注册 ROT：

**路径一：`CoCreateInstance`（创建新实例）**

```
你的程序 ──CoCreateInstance──> 查注册表 ProgID ──> 启动 SOLIDWORKS.exe
                                                    └─ 新实例
```

程序自己启动的实例，**默认不注册 ROT**。因为 COM 的语义是：
"我创建了一个对象，我知道它的接口指针，我用指针调用就行，为什么要全局登记？"

**路径二：`GetActiveObject`（粘到已有实例）**

```
你的程序 ──GetActiveObject──> 查 ROT 表 ──> 找到已有实例的 IUnknown
```

这条路径要求对象**已经在 ROT 里**。而谁往里放？**是应用自己。**

### 2.2 SolidWorks 什么时候注册

SolidWorks 的启动流程大概是这样：

```
用户双击桌面图标
  ↓
SOLIDWORKS.exe 启动
  ↓
初始化 UI、加载插件、打开许可
  ↓
【注册到 ROT】         ← 就是这一步
  ↓
显示主窗口，进入消息循环
```

**关键：注册 ROT 是在「交互式启动」的分支里做的。**

而通过 COM 后台拉起时，走的是另一条分支：

```
CoCreateInstance
  ↓
OLE 启动 SOLIDWORKS.exe（带 -RegServer 或内部标志）
  ↓
初始化 COM 对象、加载许可
  ↓
【不注册 ROT】         ← 跳过
  ↓
隐藏窗口，只等待接口调用
```

所以：

| 启动方式 | 有主窗口 | 在 ROT 里 |
|---|---|---|
| 用户双击图标 | ✅ | ✅ |
| 你的 `Dispatch()` 后台拉起 | ❌（或隐藏） | ❌ |
| 已经手动开着，你再 `Dispatch()` | ✅ | ✅ |

---

## 三、最坑的地方：它"看起来"成功了

这是很多人卡住的真正原因 —— **后台拉起的实例，`Dispatch` 是成功的**。

```python
import win32com.client

sw = win32com.client.Dispatch("SldWorks.Application")
print(sw)                    # <win32com.gen_py.SldWorks...>
print(sw.RevisionNumber())   # '33.5.0'   ← 能用！
```

`Dispatch` 会先查 ROT，找不到就**自动 fallback 到 CoCreateInstance**。
所以你拿到了一个**能用的**对象。

**但是**：

```python
print(sw.Visible)            # False —— 没有窗口
print(sw.GetDocumentCount()) # 0
```

更糟的是 —— 如果你在这之前已经用过 `GetActiveObject` 并且失败了，
你的代码里可能留下了一个"降级到 Dispatch"的逻辑，然后一切看起来正常，
**直到你要给用户看结果的时候**：

> "为什么我的脚本跑完了，SolidWorks 界面一片空白？"

因为那个实例是隐藏的，而且可能根本不是你以为的那个。

### 真实案例（本项目的坑）

swforge 的早期版本就是这样：

```python
# v0.4 的写法
try:
    sw = win32com.client.GetActiveObject("SldWorks.Application")
except Exception:
    sw = win32com.client.Dispatch("SldWorks.Application")   # 静默降级
```

问题在于：**降级之后没有任何提示**。

用户看到的是"成功了"，实际拿到的是一个隐藏实例。
更隐蔽的是 —— 那个隐藏实例**还悄悄占着内存和许可**，
跑几次之后机器上堆了四五个看不见的 SOLIDWORKS.exe。

---

## 四、正确做法

### 4.1 两级 fallback + **真实往返探测**

```python
import win32com.client
import pythoncom


def connect_solidworks():
    """连接 SolidWorks：先找已有实例，没有就创建，并且都要验证真的能用。"""

    # ---- 第一级：找 ROT 里的已有实例
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
        if _is_usable(sw):
            return sw, "attached"        # 粘到了用户已打开的实例
    except pythoncom.com_error:
        pass                              # ROT 里没有，正常，往下走

    # ---- 第二级：创建新实例
    try:
        sw = win32com.client.Dispatch("SldWorks.Application")
        if _is_usable(sw):
            return sw, "created"         # 新建的实例
    except pythoncom.com_error as exc:
        raise RuntimeError(
            "无法连接 SolidWorks。\n"
            "可能原因：\n"
            "  1. 没有安装 SolidWorks\n"
            "  2. 许可服务未启动（检查 SolidWorks Licensing Service）\n"
            "  3. 32 位/64 位不匹配（本项目需要 64 位 Python）\n"
            f"原始错误：{exc}"
        )

    raise RuntimeError("SolidWorks 对象创建了但不可用")


def _is_usable(sw) -> bool:
    """真实往返探测 —— 光判断非 None 不够。"""
    if sw is None:
        return False
    try:
        rev = sw.RevisionNumber()        # 调一个简单方法，确认真的活着
        count = sw.GetDocumentCount()    # 再调一个，确认不是空壳
        return bool(rev) and count >= 0
    except Exception:
        return False
```

### 4.2 为什么要"真实往返"

因为 `Activator.CreateInstance` / `Dispatch` **有时候返回一个空壳代理**：

- 对象非 `None`
- 属性读出来是 `None` 或 0
- 一调方法就抛异常，或者更糟 —— 静默返回错误值

**只看非空会误判成成功。** 必须调一个真实方法：

```python
# ❌ 不够
if sw is not None:
    ...

# ✅ 够
if sw is not None and sw.RevisionNumber():
    ...
```

### 4.3 C# 版本（本项目实际用的）

```csharp
static ISldWorks Connect() {
    string e1 = "", e2 = "";

    // 第一级：ROT
    try {
        ISldWorks s = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
        if (Usable(s)) return s;
        e1 = "空壳";
    } catch (Exception ex) { e1 = ex.GetType().Name; }

    // 第二级：新建
    try {
        Type t = Type.GetTypeFromProgID("SldWorks.Application");
        if (t != null) {
            ISldWorks s = (ISldWorks)Activator.CreateInstance(t);
            if (Usable(s)) return s;
            e2 = "空壳";
        }
    } catch (Exception ex) { e2 = ex.GetType().Name; }

    throw new Exception("无法连接 SolidWorks（" + e1 + " / " + e2 + "）");
}

static bool Usable(ISldWorks s) {
    if (s == null) return false;
    try { return !String.IsNullOrEmpty(s.RevisionNumber()) && s.GetDocumentCount() >= 0; }
    catch { return false; }
}
```

注意错误信息里**把两级的失败原因都带上**（`e1 / e2`）。
这样用户拿到报错时能直接判断是"ROT 里没有且创建失败"还是"创建了但是空壳"。

---

## 五、如果你就是想让后台实例有窗口

有两条路：

### 5.1 显式设 `Visible = true`

```python
sw = win32com.client.Dispatch("SldWorks.Application")
sw.Visible = True          # 强制显示主窗口
```

**注意**：这只能让窗口出现，**不会让它注册进 ROT**。
也就是说，你的**另一个**程序仍然 `GetActiveObject` 找不到它。

### 5.2 让用户先手动启动（推荐）

对自动化工具来说，最稳的约定是：

> **SolidWorks 必须由用户先手动启动，主窗口可见，然后工具再连接。**

理由：
1. 用户能看到发生了什么（不会出现"跑完了但界面空白"）
2. 许可、插件、模板都已经初始化完毕
3. 出问题时用户能直接看到弹窗（比如许可过期、文件只读）

swforge 的 README 里就是这么写的：

> **SolidWorks must be started manually and its main window fully visible**,
> otherwise the live tests fail.

---

## 六、排查清单

如果你的 `GetActiveObject` 失败了，按这个顺序查：

```
□ 1. SolidWorks 现在有主窗口吗？
     任务管理器里看到 SLDWORKS.exe 但桌面没窗口 → 它是后台实例，不在 ROT

□ 2. 错误码是 0x800401E3 (MK_E_UNAVAILABLE) 吗？
     是 → ROT 里没有，正常现象，用 Dispatch fallback
     否 → 往下看

□ 3. 错误码是 0x800401F3 (CO_E_CLASSSTRING) 吗？
     是 → ProgID 无效。检查：
          - 装的是不是纯 Viewer（Viewer 不注册 COM）
          - 注册表里有没有 HKEY_CLASSES_ROOT\SldWorks.Application

□ 4. Python 是 64 位吗？
     import platform; platform.architecture()
     SolidWorks 是 64 位，32 位 Python 连不上

□ 5. 是不是 pywin32 的缓存问题？
     python -c "import win32com; win32com.client.gencache.Rebuild()"
```

---

## 七、这件事的教训

### 一个 API 失败，先查它的语义，别先猜实现

`GetActiveObject` 的名字已经说明了一切：**Get ACTIVE Object**。
"Active" 在 COM 里是有明确定义的 —— 在 ROT 里注册过的。
不是"正在运行的对象"。

如果先查了文档，就不会写 `try/except` 兜底了 ——
而会直接意识到「这条路径本来就可能没有，我需要两条路」。

### 静默降级是最危险的写法

```python
try:
    sw = GetActiveObject(...)
except:
    sw = Dispatch(...)      # 用户永远不知道走了哪条
```

**降级本身没错，静默降级有问题。** 至少应该：

```python
mode = "attached"   # 或 "created"
print(f"已连接 SolidWorks（{mode}）")
```

swforge 现在的返回值里就带这个字段，调用方能知道自己是粘到了用户的实例，
还是自己新建了一个。

### "非空 = 成功"是个陷阱

这个教训在本项目里出现了不止一次：

| 场景 | 假成功 | 真判据 |
|---|---|---|
| COM 连接 | 对象非 None | `RevisionNumber()` 返回值 |
| 配合 | `FixComponent()` 返回 None | `IsFixed` 属性 |
| 材质 | `material="Q235"` 被接受 | 质量 / 体积回读 |
| 干涉 | API 返回成功 | 重叠体积数值 |
| 特征 | 特征数 +1 | 实体数回读 |

**统一原则：判据必须是独立回读，不能是调用方的返回值。**

---

## 参考

- 项目源码：https://github.com/mwdandoms/swforge
- 完整踩坑记录：https://github.com/mwdandoms/swforge/blob/main/docs/pitfalls.md
- Microsoft Docs: [`IMarshal.GetActiveObject`](https://learn.microsoft.com/en-us/windows/win32/api/objbase/nf-objbase-getactiveobject)
- Microsoft Docs: [Running Object Table](https://learn.microsoft.com/en-us/windows/win32/com/running-object-table)
- SolidWorks API Help: `ISldWorks` interface

---

*本文基于 swforge v0.8.0 的实测经验，环境：SolidWorks 2025 SP5.0 + Python 3.14.3 + pywin32 312。*
