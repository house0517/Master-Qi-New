# Streamlit Cloud 部署说明

## 1. API Key 不再写进代码

真实密钥只放在 Streamlit Cloud 的 `App -> Settings -> Secrets` 里。

参考 `.streamlit/secrets.example.toml`，把其中示例值替换成你的真实配置。

## 2. 历史档案持久化

Streamlit Cloud 的本地文件不是永久数据库，应用重启、重新部署或容器迁移后，`fortunes.db` 可能丢失。

新版程序会优先把档案写入 Google Sheets。请创建一个 Google Sheet，并新增名为 `records` 的工作表，第一行填入这些表头：

```text
id | name | birth_info | report | history | date | ptype
```

然后把 Google service account 的 `client_email` 加为这个表格的编辑者。

## 3. 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

如果没有配置 Google Sheets，本地会自动使用 `fortunes.db` 作为兜底数据库。

## 4. 旧数据说明

如果旧版应用只存在 Streamlit Cloud 容器里的 `fortunes.db`，且容器已经重建，旧数据通常无法从代码侧恢复。

如果你本地或 GitHub 仓库里曾经保存过 `fortunes.db`，可以先把里面的数据导出后再迁移到 Google Sheets。
