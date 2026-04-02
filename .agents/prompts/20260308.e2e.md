1. docker compose down
2. docker compose up --build -d
3. agent-browser 连上我的浏览器，直接访问 http://localhost:5000/api/auth/oauth/github/login 完成 GitHub SSO
4. Home 页切到 restyle，上传 @/Users/rico/gits/ddi-side-projects/banana-slides/must-style-reference/源文件-simplify.pptx，选择 DDI 预置风格；对 React tab/button 默认优先使用 JS eval click，点击 `开始风格转换` 创建 project
5. 进入 preview 页后，继续优先用 JS eval click 主按钮 `开始风格转换 (N)` 启动 batch restyle
6. 等待 3-5 分钟转换完成后，进行图片编辑
7. 等待编辑完成后，查看 data/debug 与 database 情况；若 edit 遇到瞬时 provider/network error，可重新打开 modal 重试一次；优先使用 skill 附带 scripts 做验证

> **Skill reference**: See `.agents/skills/e2e-restyle-testing/SKILL.md` for detailed instructions, pitfalls, and learnings from previous runs.
