# Community validation / 社区版验证

## Scope

Community 1.7.0 contains 66 internal MCP operations behind four public gateways. Advanced GB review and rule orchestration implementations are absent; their tests are not counted as Community tests.

- Offline regression: 289 passed, 32 SW-marked tests deselected on the local Windows/Python 3.14 environment.
- Independent native Community fixture: Q235 plate 120×80×20, packaged A3 template native frame/unit/projection/style readback, new PDF export and artifact freshness passed on SW2025 SP5.
- That Community native run began and ended with zero open SW documents, PID unchanged.
- The full local candidate additionally exercised A0–A4 templates, saved/reopened flatness, assembly variants/BOM and drawing books. These are bounded fixtures, not a full acceptance matrix for every input or machine.

## Boundaries / 边界

仅SW2025 SP5实机，未验证其他SW版本。基础图框为GB导向配置，不是全条文认证。字体未认证精确长仿宋；配合表仅H6/H7/H8/h6/h7/h8/g6、3<D<=500mm，Ra为有限优先系列。不支持的代号表示库未覆盖，不代表其被标准禁止。

GD&T interfaces: flatness, parallelism, perpendicularity, position, circular_runout. Saved/reopened native fixture: flatness. No straightness interface is claimed.

Document fingerprints/approval tokens protect local workflows; they are not certified electronic signatures. Drawing checks do not establish manufacturing readiness. Complex assemblies, numbering, font glyphs and final drawing content require engineering review.

Public distribution checks reject withheld implementation files in source archives and wheels. See COMMUNITY_SCOPE.json.
