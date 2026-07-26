# 前端部署

ChainLens 的前端是 `web/` 下的静态站点，可以部署到 GitHub Pages 或 Cloudflare Pages。页面不保存密钥；没有 API 地址时展示脱敏聚合快照，配置 API 后可以查询实时 DuckDB 结果。

## GitHub Pages

1. 把仓库推送到 GitHub。
2. 打开仓库 `Settings -> Pages`，将 `Source` 设为 `GitHub Actions`。
3. 修改 `web/config.js`：

```javascript
window.CHAINLENS_API_URL = "https://你的-api-域名";
```

4. 推送后等待 `Deploy static frontend` workflow 完成。

如果暂时没有公网 API，保持空字符串即可，页面仍然能展示四个场景的脱敏聚合快照和交互。

## Cloudflare Pages

- Framework preset：`None`
- Build command：留空
- Output directory：`web`
- 部署后在 `web/config.js` 写入 API 地址并重新部署

## 启动实时 API

API 需要能读取 `data/warehouse/chainlens.duckdb`：

```powershell
cd G:\chainlens
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

生产环境要把 `allow_origins=["*"]` 收紧为实际前端域名，并在反向代理层加访问控制、限流和 HTTPS。GitHub Pages 本身不能运行 Python、DuckDB 或数据库密钥，因此只能承担静态前端。
