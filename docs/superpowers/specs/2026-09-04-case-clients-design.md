# 案件管理 · 客户档案（2026-09-04）

## 目标
- 管理后台新增一级菜单「案件管理」，二级：案件、客户（默认案件）。
- 「权限管理」仅保留软件用户 / 角色 / 功能；委托客户与系统用户分离。
- 本期客户独立建档，不关联案件；后续再做案件-客户关联。

## 数据
表 `clients`：
- `id`, `name`, `client_type`（`person`|`enterprise`）, `id_number`（唯一）, `created_at`, `updated_at`, `created_by`
- 个人识别号=身份证号；企业=统一社会信用代码

## API
- `GET/POST /api/admin/clients`
- `PUT/DELETE /api/admin/clients/{id}`
- 权限：`cap.case_manage`（与案件同属办案行政能力）

## 菜单
概览 | 权限管理（用户/角色/功能）| 案件管理（案件/客户）| 工具管理
