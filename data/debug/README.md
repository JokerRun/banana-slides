# Debug Artifacts

这个目录是运行期调试产物的宿主机落盘目录。

- 宿主机路径：`data/debug`
- 容器内路径：`/app/debug`
- docker 挂载：`./data/debug:/app/debug`

当前主要内容是 `restyle-context/`，用于追踪 restyle 首轮生成与后续多轮编辑。
`export_restyle_debug_excel.py` 可把这些 artifact 和数据库记录汇总成 Excel；导出的 `project_name` 列优先使用历史页显式重命名的 `projects.project_name`，为空时回退到 `idea_prompt`。

## 当前范围

这套 debug 现在覆盖两条链路：

- 首轮 restyle
  - 入口：预览页点击“开始进行风格转换”
  - 对应 task_type：`RESTYLE_IMAGES`
  - 粒度：一个 task 可能对应多页

- restyle edit
  - 入口：预览页里对某一页点击“编辑”再生成新版本
  - 对应 task_type：`EDIT_PAGE_IMAGE`
  - 粒度：一个 task 通常只对应一页，并生成一个新 page version

还不覆盖：

- 上传 PPT/PDF 的解析细节
- 建立 restyle project 的完整取证
- 非 restyle 项目的普通生成流程

## 为什么现在先用 debug

现在 debug 是“数据库化之前的探路层”。

我们已经开始把 trace 粒度往这几层收敛：

```text
project
  -> task
    -> page
      -> page version
```

未来如果要落数据库，当前 JSON artifact 里的核心字段会优先沿用，而不是重新发明一套。

## 写入条件

满足任一条件就会写 artifact：

- `.env` 里 `DEBUG_RESTYLE_CONTEXT=true`
- 本次上下文 degraded
- 本次发生 provider fallback
- 本次发生 error

当前仓库 `.env` 已开启：`DEBUG_RESTYLE_CONTEXT=true`。

## 主目录说明

- [restyle-context/README.md](file:///Users/rico/gits/ddi-side-projects/banana-slides/data/debug/restyle-context/README.md)

这个子目录 README 会具体解释：

- task/page/version 粒度
- 首轮 restyle 和 edit restyle 的目录差异
- 哪些文件会出现
- 是否覆盖
- 如何手动清理

## 生命周期行为

### 不会自动清空

因为 `data/debug` 是宿主机目录：

- 重启容器不会清空
- 重建容器不会清空
- 只有手动删目录才会清空

### 不影响业务数据

删除 `data/debug` 只影响调试证据，不影响：

- 数据库里的 task 记录
- 页面版本 `page_image_versions`
- 已保存图片文件

## 推荐排查顺序

如果你要查某次 restyle/edit：

1. 先找对应 `task_id`
2. 再区分它是首轮 `RESTYLE_IMAGES` 还是编辑 `EDIT_PAGE_IMAGE`
3. 然后进入 `data/debug/restyle-context/<task_id>/`
4. 先看 `provider_result` 或 task summary
5. 再看 request/context 类文件

ASCII 图：

```text
project
  -> task_id
    -> restyle-context/<task_id>/
      -> task/...
      -> pages/...
      -> or root event files for single-page edit
```
