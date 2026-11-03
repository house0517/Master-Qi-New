# 老版测算系统：云端档案配置

本次复用订阅版 Supabase 存储，默认使用独立的 `master_qi_records` 表，不覆盖订阅版的 `records` 表。已支持自动存档、姓名搜索、调取正文与追问、下载全部记录备份、本地未同步记录补传。相同姓名、生日和测算类型覆盖更新；不同类型分开保存。

1. 在现有 Supabase 项目的 SQL Editor 执行本仓库 `supabase_schema.sql`，创建老版专用表。该脚本不删除旧数据，不修改订阅版表。
2. 在老版 Streamlit 应用的 Settings → Secrets 中添加或更新以下配置，API 配置保留；已存在 `[storage]` 时合并到原段，不要重复声明。

```toml
[storage]
backend = "supabase"
table = "master_qi_records"
worksheet = "records"

[supabase]
url = "填写现有 Supabase Project URL"
service_role_key = "填写现有项目的 secret key 或 service_role key"
```

可在 Supabase 项目页面取得 URL 和密钥；密钥只填入 Streamlit Secrets，不提交 GitHub，不粘贴到聊天。

3. 保存配置后打开老版网站，档案库应显示 `Supabase Postgres 云端持久化` 及表名 `master_qi_records`。配置显示不等于连接验证成功：如果出现读取失败，仍需检查表和密钥。
4. 点击“将本地未同步记录保存到云端”，补传仍在服务器上的记录。云端已存在的同一人、生日、类型不会被迁移流程覆盖。服务器已经丢失的历史记录不能由本功能恢复。
5. 点击“刷新档案列表”，搜索一个已保存姓名并调取，确认正文和追问完整；刷新浏览器后再次调取验证。没有配置云端时，界面会明确提示仅保存到临时 SQLite。

验证范围：9 项离线存储测试通过；完整页面检查和线上云端验证状态以实际交付说明为准。
