# Community 1.7 migration / 社区版迁移

MCP: only sw_discover, sw_describe, sw_invoke and sw_status are public.
Call sw_invoke(name="sw_validate_part", args={...}) instead of directly calling sw_validate_part.
社区版包含66个内部操作；高级GB审查、栅格审图、整套一致性与工艺规则编排不包含在本次分发。
Advanced GB review and rule orchestration are not included in this distribution.
Existing Community Python/CLI entry points remain. Admin operations are disabled by default; destructive actions require explicit approval.
