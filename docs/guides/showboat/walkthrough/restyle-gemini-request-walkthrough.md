# Banana Slides Restyle 链路与 Gemini Request Walkthrough

*2026-03-28T05:09:21Z by Showboat 0.6.1*
<!-- showboat-id: eae0f484-cafd-4d69-b7df-10eb5e64ff33 -->

## 范围 Scope

本文只聚焦 `restyle` pipeline，不展开其他生成链路。

本文采用的默认前提：

- default provider format 是 `gemini`
- default image model 是 `gemini-3-pro-image-preview`
- default aspect ratio / resolution 是 `16:9` 与 `2K`
- 核心问题是：真正发起 Gemini image call 之前，request shape 到底是怎么组出来的？

## 线性主链路 Linear Map

- 首轮 First pass：`Frontend API -> restyle controller -> create Task -> task_manager.restyle_images_task -> get_restyle_prompt() -> AIService.image_provider.generate_image() -> GenAI client.models.generate_content()`
- 编辑轮 Edit round：`page_controller.edit/image -> task_manager.edit_page_image_task -> build_restyle_edit_context() -> AIService.edit_restyle_image_with_context() -> GenAI generate_image_from_conversation()`

下文严格按这个顺序展开，目的是让你顺着源码读一遍，就能把整条链路一次性装进脑子里。

```bash
rg -n 'restyleGenerate|restyleSinglePage|@restyle_bp.route|def restyle_images_task|def edit_page_image_task|def get_restyle_prompt|def build_restyle_edit_context|def edit_restyle_image_with_context|def generate_image_from_conversation' frontend/src/api/endpoints.ts backend/controllers/restyle_controller.py backend/controllers/page_controller.py backend/services/task_manager.py backend/services/prompts.py backend/services/restyle_edit_context.py backend/services/ai_service.py backend/services/ai_providers/image/genai_provider.py | LC_ALL=C sort
```

```output
backend/controllers/restyle_controller.py:192:@restyle_bp.route('/<project_id>/restyle/generate', methods=['POST'])
backend/controllers/restyle_controller.py:271:@restyle_bp.route('/<project_id>/pages/<page_id>/restyle/generate', methods=['POST'])
backend/controllers/restyle_controller.py:55:@restyle_bp.route('/restyle', methods=['POST'])
backend/services/ai_providers/image/genai_provider.py:253:    def generate_image_from_conversation(
backend/services/ai_service.py:563:    def edit_restyle_image_with_context(self, context, aspect_ratio='16:9', resolution='2K', trace_context=None):
backend/services/prompts.py:781:def get_restyle_prompt(
backend/services/restyle_edit_context.py:304:def build_restyle_edit_context(
backend/services/task_manager.py:1232:def restyle_images_task(task_id: str, project_id: str, ai_service, file_service,
backend/services/task_manager.py:638:def edit_page_image_task(task_id: str, project_id: str, page_id: str,
frontend/src/api/endpoints.ts:861:export const restyleGenerate = async (
frontend/src/api/endpoints.ts:875:export const restyleSinglePage = async (
```

## 1. 前端入口 Frontend Entry

这里的 frontend 层非常薄。它不负责拼 `prompt`，不负责组 Gemini payload，也不知道 `contents[]` 的最终结构。

它只是在两个 backend entrypoint 之间做选择：

- 批量首轮 restyle：`/api/projects/{projectId}/restyle/generate`
- 单页首轮 restyle：`/api/projects/{projectId}/pages/{pageId}/restyle/generate`

所以真正有意思的逻辑，都是 request 进入 Flask 之后才开始。

```bash
nl -ba frontend/src/api/endpoints.ts | sed -n '858,882p'
```

```output
   858	/**
   859	 * 启动 restyle 生成（批量）
   860	 */
   861	export const restyleGenerate = async (
   862	  projectId: string,
   863	  pageIds?: string[]
   864	): Promise<ApiResponse<{ task_id: string; status: string; total_pages: number }>> => {
   865	  const response = await apiClient.post<ApiResponse<{ task_id: string; status: string; total_pages: number }>>(
   866	    `/api/projects/${projectId}/restyle/generate`,
   867	    { page_ids: pageIds }
   868	  );
   869	  return response.data;
   870	};
   871	
   872	/**
   873	 * 启动单页 restyle 生成
   874	 */
   875	export const restyleSinglePage = async (
   876	  projectId: string,
   877	  pageId: string
   878	): Promise<ApiResponse<{ task_id: string; status: string }>> => {
   879	  const response = await apiClient.post<ApiResponse<{ task_id: string; status: string }>>(
   880	    `/api/projects/${projectId}/pages/${pageId}/restyle/generate`
   881	  );
   882	  return response.data;
```

## 2. Gemini 调用前的项目创建 Project Creation

创建一个 restyle project 时，会上传：

- 一个 PPT / PPTX / PDF source file
- 一到五张 style reference images **或** `style_preset_id`（如 `ddi-standard`；遗留 `ddi` / `ddi-restyle-v2` 会规范为 canonical id）。传预置 id 时后端从 `assets/presets/` 复制底图到项目 `style_refs`，并写入 `style_preset_id` / `style_preset_version` / `style_preset_sha256`。
- 可选的 `restyle_prompt`（与 canonical `prompt-restyle.md` 相同时由后端走预置正文）

控制器 controller 层会先把这些资产持久化，再把源 deck 拆成逐页 PNG，最后才创建 `Page` rows。所以后续每一次 Gemini 调用，吃的都是磁盘上已经落好的文件，不是临时 request blob。预置元数据与底图对外暴露为 `GET /api/presets` 与 `GET /api/presets/<id>/image`。

```bash
nl -ba backend/controllers/restyle_controller.py | sed -n '55,184p'
```

```output
    55	@restyle_bp.route('/restyle', methods=['POST'])
    56	def create_restyle_project():
    57	    """
    58	    POST /api/projects/restyle - Create a restyle project
    59	
    60	    Multipart form data:
    61	    - source_file: File (PPT/PDF) — required
    62	    - style_refs: File[] (optional when style_preset_id is provided)
    63	    - style_preset_id: str (optional; legacy ddi/ddi-restyle-v2 accepted)
    64	    - restyle_prompt: str (optional custom restyle prompt)
    64	
    65	    Flow:
    66	    1. Save source file
    67	    2. Convert source file to per-page PNG images
    68	    3. Save style reference images
    69	    4. Create Project + Pages in DB
    70	    5. Return project with original slide previews
    71	    """
    72	    try:
    73	        # Validate source file
    74	        if 'source_file' not in request.files:
    75	            return bad_request("source_file is required")
    76	
    77	        source_file = request.files['source_file']
    78	        if not source_file.filename or not _allowed_source_file(source_file.filename):
    79	            return bad_request(f"Invalid source file. Supported: {', '.join(ALLOWED_SOURCE_EXTENSIONS)}")
    80	
    81	        # Validate style refs
    82	        style_refs = request.files.getlist('style_refs')
    83	        if not style_refs or len(style_refs) == 0:
    84	            return bad_request("At least one style reference image is required")
    85	        if len(style_refs) > MAX_STYLE_REFS:
    86	            return bad_request(f"Maximum {MAX_STYLE_REFS} style reference images allowed")
    87	
    88	        for ref in style_refs:
    89	            if not ref.filename or not _allowed_image_file(ref.filename):
    90	                return bad_request(f"Invalid style reference image: {ref.filename}")
    91	
    92	        restyle_prompt = request.form.get('restyle_prompt', '').strip()
    93	
    94	        # Use source filename (without extension) as project name
    95	        source_name = Path(source_file.filename).stem or 'Restyle Project'
    96	
    97	        # Create project
    98	        project = Project(
    99	            owner_id=get_current_user_id(),
   100	            creation_type='restyle',
   101	            idea_prompt=source_name,
   102	            restyle_prompt=restyle_prompt if restyle_prompt else None,
   103	            status='DRAFT'
   104	        )
   105	        db.session.add(project)
   106	        db.session.flush()  # Get project ID
   107	
   108	        from services import FileService
   109	        file_service = FileService(current_app.config['UPLOAD_FOLDER'])
   110	
   111	        # Save source file
   112	        project_dir = file_service._get_project_dir(project.id)
   113	        source_dir = project_dir / 'source'
   114	        source_dir.mkdir(exist_ok=True, parents=True)
   115	
   116	        source_filename = _safe_filename_with_original_ext(
   117	            source_file.filename,
   118	            default_stem='source_file'
   119	        )
   120	        source_path = source_dir / source_filename
   121	        source_file.save(str(source_path))
   122	        project.source_file_path = source_path.relative_to(file_service.upload_folder).as_posix()
   123	
   124	        logger.info(f"📁 Source file saved: {source_path} ({os.path.getsize(str(source_path)) / 1024:.1f} KB)")
   125	
   126	        # Save style reference images
   127	        style_ref_dir = project_dir / 'style_refs'
   128	        style_ref_dir.mkdir(exist_ok=True, parents=True)
   129	
   130	        style_ref_paths = []
   131	        for i, ref in enumerate(style_refs):
   132	            ref_ext = Path(ref.filename).suffix.lower().lstrip('.')
   133	            if ref_ext not in ALLOWED_IMAGE_EXTENSIONS:
   134	                ref_ext = 'png'
   135	            saved_name = f"style_ref_{i + 1}.{ref_ext}"
   136	            ref_path = style_ref_dir / saved_name
   137	            ref.save(str(ref_path))
   138	            rel_path = ref_path.relative_to(file_service.upload_folder).as_posix()
   139	            style_ref_paths.append(rel_path)
   140	            logger.info(f"🎨 Style ref {i + 1}/{len(style_refs)} saved: {ref_path} ({os.path.getsize(str(ref_path)) / 1024:.1f} KB)")
   141	
   142	        project.set_style_ref_image_paths(style_ref_paths)
   143	
   144	        # Convert source file to images
   145	        restyle_service = RestyleService()
   146	        pages_dir = file_service._get_pages_dir(project.id)
   147	        originals_dir = str(pages_dir / 'originals')
   148	        os.makedirs(originals_dir, exist_ok=True)
   149	
   150	        logger.info(f"📄 Converting source file to images: {source_filename}")
   151	        slide_images = restyle_service.convert_to_images(str(source_path), originals_dir)
   152	        logger.info(f"✅ Converted {len(slide_images)} pages from {source_filename}")
   153	
   154	        # Create Page records
   155	        pages_list = []
   156	        for i, img_path in enumerate(slide_images):
   157	            rel_path = os.path.relpath(img_path, str(file_service.upload_folder))
   158	            page = Page(
   159	                project_id=project.id,
   160	                order_index=i,
   161	                original_slide_image_path=rel_path,
   162	                status='DRAFT'
   163	            )
   164	            # Set minimal outline content (page number as title)
   165	            page.set_outline_content({
   166	                'title': f'Slide {i + 1}',
   167	                'points': []
   168	            })
   169	            db.session.add(page)
   170	            pages_list.append(page)
   171	
   172	        project.status = 'SLIDES_EXTRACTED'
   173	        project.updated_at = datetime.utcnow()
   174	        db.session.commit()
   175	
   176	        logger.info(f"✅ Restyle project created: id={project.id}, name='{source_name}', pages={len(pages_list)}, style_refs={len(style_refs)}, prompt={'yes' if restyle_prompt else 'no'}")
   177	
   178	        return success_response({
   179	            'project_id': project.id,
   180	            'creation_type': 'restyle',
   181	            'status': project.status,
   182	            'pages': [page.to_dict() for page in pages_list],
   183	            'total_pages': len(pages_list)
   184	        }, status_code=201)
```

```bash
nl -ba backend/services/restyle_service.py | sed -n '15,106p'
```

```output
    15	class RestyleService:
    16	    """PPT/PDF → slide images → restyle → new PPTX"""
    17	
    18	    def convert_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    19	        """
    20	        将PPT/PDF转为逐页PNG图片
    21	
    22	        Args:
    23	            file_path: 源文件路径 (.pptx/.ppt/.pdf)
    24	            output_dir: 输出目录
    25	            dpi: 输出分辨率 (default 300)
    26	
    27	        Returns:
    28	            PNG图片路径列表, 按页码排序
    29	        """
    30	        ext = Path(file_path).suffix.lower()
    31	        os.makedirs(output_dir, exist_ok=True)
    32	
    33	        if ext in ('.ppt', '.pptx'):
    34	            return self._pptx_to_images(file_path, output_dir, dpi)
    35	        elif ext == '.pdf':
    36	            return self._pdf_to_images(file_path, output_dir, dpi)
    37	        else:
    38	            raise ValueError(f"Unsupported file format: {ext}. Supported: .pptx, .ppt, .pdf")
    39	
    40	    def _pptx_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    41	        """
    42	        PPT/PPTX → PDF (via LibreOffice) → PNG[]
    43	
    44	        Pipeline:
    45	            PPT/PPTX --LibreOffice headless--> PDF --PyMuPDF--> PNG[]
    46	        """
    47	        # Step 1: LibreOffice headless → PDF
    48	        with tempfile.TemporaryDirectory() as tmp_dir:
    49	            logger.info(f"Converting PPT to PDF via LibreOffice: {file_path}")
    50	
    51	            # Try different LibreOffice paths
    52	            libreoffice_cmd = self._find_libreoffice()
    53	
    54	            result = subprocess.run(
    55	                [
    56	                    libreoffice_cmd,
    57	                    '--headless',
    58	                    '--convert-to', 'pdf',
    59	                    '--outdir', tmp_dir,
    60	                    file_path
    61	                ],
    62	                capture_output=True, text=True, timeout=120
    63	            )
    64	
    65	            if result.returncode != 0:
    66	                logger.error(f"LibreOffice conversion failed: {result.stderr}")
    67	                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
    68	
    69	            # Find the generated PDF
    70	            pdf_files = list(Path(tmp_dir).glob('*.pdf'))
    71	            if not pdf_files:
    72	                raise RuntimeError("LibreOffice did not generate PDF output")
    73	
    74	            pdf_path = str(pdf_files[0])
    75	            logger.info(f"PDF generated: {pdf_path}")
    76	
    77	            # Step 2: PDF → PNG
    78	            return self._pdf_to_images(pdf_path, output_dir, dpi)
    79	
    80	    def _pdf_to_images(self, file_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    81	        """
    82	        PDF → PNG[] via PyMuPDF (fitz)
    83	        """
    84	        import fitz  # PyMuPDF
    85	
    86	        os.makedirs(output_dir, exist_ok=True)
    87	        logger.info(f"Converting PDF to images: {file_path} (dpi={dpi})")
    88	        doc = fitz.open(file_path)
    89	        image_paths = []
    90	
    91	        zoom = dpi / 72  # PDF base resolution is 72 dpi
    92	        matrix = fitz.Matrix(zoom, zoom)
    93	
    94	        for page_num in range(len(doc)):
    95	            page = doc[page_num]
    96	            pix = page.get_pixmap(matrix=matrix)
    97	
    98	            output_path = os.path.join(output_dir, f"slide_{page_num + 1:03d}.png")
    99	            pix.save(output_path)
   100	            image_paths.append(output_path)
   101	
   102	            logger.debug(f"Page {page_num + 1}/{len(doc)} → {output_path} ({pix.width}x{pix.height})")
   103	
   104	        doc.close()
   105	        logger.info(f"Converted {len(image_paths)} pages to PNG images")
   106	        return image_paths
```

```bash
nl -ba backend/models/project.py | sed -n '16,31p'; printf '\n'; nl -ba backend/models/page.py | sed -n '17,27p'
```

```output
    16	    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    17	    owner_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, index=True)
    18	    idea_prompt = db.Column(db.Text, nullable=True)
    19	    outline_text = db.Column(db.Text, nullable=True)  # 用户输入的大纲文本（用于outline类型）
    20	    description_text = db.Column(db.Text, nullable=True)  # 用户输入的描述文本（用于description类型）
    21	    extra_requirements = db.Column(db.Text, nullable=True)  # 额外要求，应用到每个页面的AI提示词
    22	    creation_type = db.Column(db.String(20), nullable=False, default='idea')  # idea|outline|descriptions|restyle
    23	    template_image_path = db.Column(db.String(500), nullable=True)
    24	    template_style = db.Column(db.Text, nullable=True)  # 风格描述文本（无模板图模式）
    25	    # Restyle 模式专用字段
    26	    source_file_path = db.Column(db.String(500), nullable=True)  # 上传的原始PPT/PDF路径
    27	    style_ref_image_paths = db.Column(db.Text, nullable=True)  # JSON: 风格参考图路径列表
    28	    brand_guidelines = db.Column(db.Text, nullable=True)  # 品牌风格规范文本
    29	    restyle_prompt = db.Column(db.Text, nullable=True)  # Restyle 自定义提示词
    30	    # 导出设置
    31	    export_extractor_method = db.Column(db.String(50), nullable=True, default='hybrid')  # 组件提取方法: mineru, hybrid

    17	    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    18	    project_id = db.Column(db.String(36), db.ForeignKey('projects.id'), nullable=False)
    19	    order_index = db.Column(db.Integer, nullable=False)
    20	    part = db.Column(db.String(200), nullable=True)  # Optional section name
    21	    outline_content = db.Column(db.Text, nullable=True)  # JSON string
    22	    description_content = db.Column(db.Text, nullable=True)  # JSON string
    23	    generated_image_path = db.Column(db.String(500), nullable=True)  # Original PNG image path
    24	    cached_image_path = db.Column(db.String(500), nullable=True)  # Compressed JPG thumbnail path
    25	    original_slide_image_path = db.Column(db.String(500), nullable=True)  # Restyle: 原始slide图片路径
    26	    restyle_base_prompt_snapshot = db.Column(db.Text, nullable=True)  # Restyle: 首轮生成prompt快照
    27	    status = db.Column(db.String(50), nullable=False, default='DRAFT')
```

### 这些字段为什么关键 Why These Fields Matter

`Project.restyle_prompt` 是 project-level 的 style instruction。

`Page.original_slide_image_path` 是不可变的 structural source image。

`Page.restyle_base_prompt_snapshot` 才是最关键的那个：首轮生成之后，该页真正使用过的 prompt 会被冻结在这里。后续 edit round 会复用它来做 style lock，而不是靠“重新猜一遍上下文”。

## 3. 首轮任务 First-Pass Restyle Task

`/restyle/generate` 和 `/pages/{page_id}/restyle/generate` 都不会 inline 调 Gemini。它们只会创建 `Task`，拿到 singleton `AIService`，然后把活丢给 `task_manager.submit_task(...)`。

真正的 request assembly，发生在这个 background task 里，而且是按页逐个组装。

```bash
nl -ba backend/controllers/restyle_controller.py | sed -n '192,327p'
```

```output
   192	@restyle_bp.route('/<project_id>/restyle/generate', methods=['POST'])
   193	def restyle_generate(project_id):
   194	    """
   195	    POST /api/projects/{id}/restyle/generate - Start batch restyle
   196	
   197	    Request body (optional):
   198	    {
   199	        "page_ids": ["id1", "id2"],  // specific pages, default: all
   200	        "max_workers": 4
   201	    }
   202	    """
   203	    try:
   204	        project = Project.query.filter_by(id=project_id, owner_id=get_current_user_id()).first()
   205	        if not project:
   206	            return not_found('Project')
   207	
   208	        if project.creation_type != 'restyle':
   209	            return bad_request("This endpoint is only for restyle type projects")
   210	
   211	        data = request.get_json() or {}
   212	        page_ids = data.get('page_ids')
   213	        max_workers = data.get('max_workers', current_app.config.get('MAX_IMAGE_WORKERS', 4))
   214	
   215	        # Get pages
   216	        pages = get_filtered_pages(project_id, page_ids)
   217	        if not pages:
   218	            return bad_request("No pages found for project")
   219	
   220	        # Create task
   221	        task = Task(
   222	            project_id=project_id,
   223	            owner_id=get_current_user_id(),
   224	            task_type='RESTYLE_IMAGES',
   225	            status='PENDING'
   226	        )
   227	        task.set_progress({
   228	            'total': len(pages),
   229	            'completed': 0,
   230	            'failed': 0
   231	        })
   232	        db.session.add(task)
   233	        db.session.commit()
   234	
   235	        # Get services
   236	        ai_service = get_ai_service()
   237	        from services import FileService
   238	        file_service = FileService(current_app.config['UPLOAD_FOLDER'])
   239	
   240	        app = current_app._get_current_object()
   241	
   242	        # Submit background task
   243	        task_manager.submit_task(
   244	            task.id,
   245	            restyle_images_task,
   246	            project_id,
   247	            ai_service,
   248	            file_service,
   249	            page_ids,
   250	            max_workers,
   251	            current_app.config['DEFAULT_ASPECT_RATIO'],
   252	            current_app.config['DEFAULT_RESOLUTION'],
   253	            app
   254	        )
   255	
   256	        project.status = 'GENERATING_IMAGES'
   257	        db.session.commit()
   258	
   259	        return success_response({
   260	            'task_id': task.id,
   261	            'status': 'GENERATING_IMAGES',
   262	            'total_pages': len(pages)
   263	        }, status_code=202)
   264	
   265	    except Exception as e:
   266	        db.session.rollback()
   267	        logger.error(f"restyle_generate failed: {str(e)}", exc_info=True)
   268	        return error_response('SERVER_ERROR', str(e), 500)
   269	
   270	
   271	@restyle_bp.route('/<project_id>/pages/<page_id>/restyle/generate', methods=['POST'])
   272	def restyle_single_page(project_id, page_id):
   273	    """
   274	    POST /api/projects/{id}/pages/{page_id}/restyle/generate - Restyle single page
   275	    """
   276	    try:
   277	        project = Project.query.filter_by(id=project_id, owner_id=get_current_user_id()).first()
   278	        if not project:
   279	            return not_found('Project')
   280	
   281	        if project.creation_type != 'restyle':
   282	            return bad_request("This endpoint is only for restyle type projects")
   283	
   284	        page = Page.query.filter_by(id=page_id, project_id=project_id).first()
   285	        if not page or page.project_id != project_id:
   286	            return not_found('Page')
   287	
   288	        # Create task
   289	        task = Task(
   290	            project_id=project_id,
   291	            owner_id=get_current_user_id(),
   292	            task_type='RESTYLE_IMAGES',
   293	            status='PENDING'
   294	        )
   295	        task.set_progress({
   296	            'total': 1,
   297	            'completed': 0,
   298	            'failed': 0
   299	        })
   300	        db.session.add(task)
   301	        db.session.commit()
   302	
   303	        # Get services
   304	        ai_service = get_ai_service()
   305	        from services import FileService
   306	        file_service = FileService(current_app.config['UPLOAD_FOLDER'])
   307	
   308	        app = current_app._get_current_object()
   309	
   310	        # Submit background task (single page)
   311	        task_manager.submit_task(
   312	            task.id,
   313	            restyle_images_task,
   314	            project_id,
   315	            ai_service,
   316	            file_service,
   317	            [page_id],  # Single page
   318	            1,  # max_workers
   319	            current_app.config['DEFAULT_ASPECT_RATIO'],
   320	            current_app.config['DEFAULT_RESOLUTION'],
   321	            app
   322	        )
   323	
   324	        return success_response({
   325	            'task_id': task.id,
   326	            'status': 'GENERATING',
   327	        }, status_code=202)
```

```bash
nl -ba backend/services/task_manager.py | sed -n '1289,1532p'
```

```output
  1289	            # Get style ref images
  1290	            style_ref_paths = project.get_style_ref_image_paths()
  1291	            restyle_prompt = project.restyle_prompt or ""
  1292	
  1293	            logger.info(f"🚀 Restyle task started: project={project_id}, pages={total_pages}, "
  1294	                        f"style_refs={len(style_ref_paths)}, prompt={'yes' if restyle_prompt else 'no'}, "
  1295	                        f"aspect_ratio={aspect_ratio}, resolution={resolution}, max_workers={max_workers}")
  1296	
  1297	            task_trace = {
  1298	                'project_id': project_id,
  1299	                'task_id': task_id,
  1300	                'flow_kind': 'first_pass_restyle',
  1301	                'page_count': total_pages,
  1302	            }
  1303	            task_started_event = {
  1304	                'project_id': project_id,
  1305	                'selected_page_ids': page_ids or [page.id for page in pages],
  1306	                'total_pages': total_pages,
  1307	                'style_ref_count': len(style_ref_paths),
  1308	                'restyle_prompt_present': bool(restyle_prompt),
  1309	                'restyle_prompt_len': len(restyle_prompt),
  1310	                'aspect_ratio': aspect_ratio,
  1311	                'resolution': resolution,
  1312	                'max_workers': max_workers,
  1313	            }
  1314	            log_restyle_edit_event('restyle_first_pass_task_started', task_trace, task_started_event)
  1315	            maybe_write_debug_artifact(
  1316	                config,
  1317	                event_name='started',
  1318	                trace=task_trace,
  1319	                payload=task_started_event,
  1320	                path_components=build_task_artifact_path_components(),
  1321	            )
  1322	
  1323	            # Load style ref images as PIL Images
  1324	            # Note: Image.open() is lazy — must .copy() to force load into memory
  1325	            # before sharing across threads, otherwise file handles may conflict
  1326	            style_ref_images = []
  1327	            style_ref_manifest = []
  1328	            for ref_path in style_ref_paths:
  1329	                abs_path = file_service.get_absolute_path(ref_path)
  1330	                style_ref_manifest.append({
  1331	                    'kind': 'style_ref',
  1332	                    'bucket': 'baseline',
  1333	                    'path': abs_path,
  1334	                    'selected': os.path.exists(abs_path),
  1335	                    'selection_reason': 'first_pass_style_ref',
  1336	                })
  1337	                if os.path.exists(abs_path):
  1338	                    img = Image.open(abs_path)
  1339	                    img.load()  # Force decode into memory
  1340	                    style_ref_images.append(img)
  1341	                    logger.info(f"🖼️  Style ref loaded: {ref_path} ({img.size[0]}x{img.size[1]})")
  1342	                else:
  1343	                    logger.warning(f"⚠️  Style ref not found: {abs_path}")
  1344	
  1345	            if not style_ref_images:
  1346	                raise ValueError("No style reference images found")
  1347	
  1348	            # Initialize progress
  1349	            task.set_progress({
  1350	                "total": total_pages,
  1351	                "completed": 0,
  1352	                "failed": 0
  1353	            })
  1354	            db.session.commit()
  1355	
  1356	            completed = 0
  1357	            failed = 0
  1358	            page_results = []
  1359	
  1360	            def restyle_single_page(page_id, page_index):
  1361	                """Restyle a single page"""
  1362	                with app.app_context():
  1363	                    page_obj = None
  1364	                    page_trace = None
  1365	                    page_artifact_path = None
  1366	                    error_stage = 'page_setup'
  1367	                    try:
  1368	                        from services.ai_service_manager import get_ai_service
  1369	                        ai_svc = get_ai_service()
  1370	
  1371	                        page_obj = Page.query.get(page_id)
  1372	                        if not page_obj:
  1373	                            raise ValueError(f"Page {page_id} not found")
  1374	
  1375	                        page_obj.status = 'GENERATING'
  1376	                        db.session.commit()
  1377	
  1378	                        source_version = PageImageVersion.query.filter_by(
  1379	                            page_id=page_id,
  1380	                            is_current=True,
  1381	                        ).first()
  1382	                        page_trace = {
  1383	                            'project_id': project_id,
  1384	                            'task_id': task_id,
  1385	                            'flow_kind': 'first_pass_restyle',
  1386	                            'page_id': page_id,
  1387	                            'page_order_index': page_obj.order_index + 1,
  1388	                            'source_version_number': source_version.version_number if source_version else None,
  1389	                            'page_version_number': None,
  1390	                        }
  1391	                        page_artifact_path = build_page_artifact_path_components(
  1392	                            page_number=page_obj.order_index + 1,
  1393	                            page_id=page_id,
  1394	                        )
  1395	
  1396	                        # Get original slide image
  1397	                        if not page_obj.original_slide_image_path:
  1398	                            raise ValueError(f"Page {page_id} has no original slide image")
  1399	
  1400	                        original_path = file_service.get_absolute_path(page_obj.original_slide_image_path)
  1401	                        if not os.path.exists(original_path):
  1402	                            raise ValueError(f"Original slide image not found: {original_path}")
  1403	
  1404	                        original_image = Image.open(original_path)
  1405	                        original_image.load()  # Force decode into memory
  1406	
  1407	                        # Build prompt with explicit style reference count for IMAGE labeling
  1408	                        prompt = get_restyle_prompt(
  1409	                            page_index=page_index,
  1410	                            total_pages=total_pages,
  1411	                            num_style_refs=len(style_ref_images),
  1412	                            custom_prompt=restyle_prompt
  1413	                        )
  1414	
  1415	                        context_event = {
  1416	                            'page_index': page_index,
  1417	                            'page_order_index': page_obj.order_index + 1,
  1418	                            'total_pages': total_pages,
  1419	                            'prompt_len': len(prompt),
  1420	                            'snapshot_present': bool(page_obj.restyle_base_prompt_snapshot),
  1421	                            'image_manifest': enrich_image_manifest([
  1422	                                {
  1423	                                    'kind': 'original_slide',
  1424	                                    'bucket': 'baseline',
  1425	                                    'path': original_path,
  1426	                                    'selected': True,
  1427	                                    'selection_reason': 'first_pass_original_slide',
  1428	                                },
  1429	                                *style_ref_manifest,
  1430	                            ]),
  1431	                        }
  1432	                        log_restyle_edit_event('restyle_first_pass_context_built', page_trace, context_event)
  1433	                        maybe_write_debug_artifact(
  1434	                            config,
  1435	                            event_name='context_built',
  1436	                            trace=page_trace,
  1437	                            payload=context_event,
  1438	                            path_components=page_artifact_path,
  1439	                        )
  1440	
  1441	                        # Build ref_images: original slide first, then style refs
  1442	                        ref_images = [original_image] + list(style_ref_images)
  1443	
  1444	                        # Generate restyled image via AIService
  1445	                        thinking_level = ai_svc._get_image_thinking_level()
  1446	                        provider_name = type(ai_svc.image_provider).__name__
  1447	                        provider_model = getattr(ai_svc.image_provider, 'model', None)
  1448	                        decision_event = {
  1449	                            'provider': provider_name,
  1450	                            'model': provider_model,
  1451	                            'thinking_level': thinking_level,
  1452	                            'ref_image_count': len(ref_images),
  1453	                        }
  1454	                        log_restyle_edit_event('restyle_first_pass_provider_decision', page_trace, decision_event)
  1455	                        maybe_write_debug_artifact(
  1456	                            config,
  1457	                            event_name='provider_decision',
  1458	                            trace=page_trace,
  1459	                            payload=decision_event,
  1460	                            path_components=page_artifact_path,
  1461	                        )
  1462	
  1463	                        request_event = {
  1464	                            'provider': provider_name,
  1465	                            'model': provider_model,
  1466	                            'prompt': prompt,
  1467	                            'prompt_len': len(prompt),
  1468	                            'aspect_ratio': aspect_ratio,
  1469	                            'resolution': resolution,
  1470	                            'thinking_level': thinking_level,
  1471	                            'ref_image_paths': [original_path, *[item['path'] for item in style_ref_manifest if item['selected']]],
  1472	                        }
  1473	                        log_restyle_edit_event('restyle_first_pass_provider_request', page_trace, {
  1474	                            'provider': provider_name,
  1475	                            'model': provider_model,
  1476	                            'prompt_len': len(prompt),
  1477	                            'ref_image_count': len(ref_images),
  1478	                        })
  1479	                        maybe_write_debug_artifact(
  1480	                            config,
  1481	                            event_name='provider_request',
  1482	                            trace=page_trace,
  1483	                            payload=request_event,
  1484	                            path_components=page_artifact_path,
  1485	                        )
  1486	                        logger.info(f"🎨 Restyling page {page_index}/{total_pages} (page_id={page_id}): "
  1487	                                    f"original={original_path} ({original_image.size[0]}x{original_image.size[1]}), "
  1488	                                    f"ref_images={len(ref_images)}, thinking_level={thinking_level}")
  1489	
  1490	                        t0 = time.time()
  1491	                        error_stage = 'provider_request'
  1492	                        image = ai_svc.image_provider.generate_image(
  1493	                            prompt=prompt,
  1494	                            ref_images=ref_images,
  1495	                            aspect_ratio=aspect_ratio,
  1496	                            resolution=resolution,
  1497	                            thinking_level=thinking_level
  1498	                        )
  1499	                        elapsed = time.time() - t0
  1500	
  1501	                        if not image:
  1502	                            raise ValueError("Failed to generate restyled image")
  1503	
  1504	                        provider_result_event = {
  1505	                            'provider': provider_name,
  1506	                            'model': provider_model,
  1507	                            'elapsed_seconds': round(elapsed, 3),
  1508	                            'result_image_size': list(image.size),
  1509	                            'error_stage': None,
  1510	                        }
  1511	                        log_restyle_edit_event('restyle_first_pass_provider_result', page_trace, provider_result_event)
  1512	                        maybe_write_debug_artifact(
  1513	                            config,
  1514	                            event_name='provider_result',
  1515	                            trace=page_trace,
  1516	                            payload=provider_result_event,
  1517	                            path_components=page_artifact_path,
  1518	                        )
  1519	
  1520	                        # Save with version management
  1521	                        error_stage = 'persist_result'
  1522	                        image_path, version = save_image_with_version(
  1523	                            image, project_id, page_id, file_service, page_obj=page_obj
  1524	                        )
  1525	
  1526	                        # Persist first-pass prompt snapshot (write-once)
  1527	                        snapshot_persisted = False
  1528	                        if not page_obj.restyle_base_prompt_snapshot:
  1529	                            page_obj.restyle_base_prompt_snapshot = prompt
  1530	                            db.session.commit()
  1531	                            snapshot_persisted = True
  1532	                            logger.info(f"📝 Snapshot persisted for page {page_id}")
```

### 用大白话解释首轮组装 First-Pass Assembly In Plain English

对每一页来说，model call 之前只会先准备三个核心输入：

1. `prompt` from `get_restyle_prompt(...)`
2. `original_image` loaded from `Page.original_slide_image_path`
3. `style_ref_images[]` loaded from `Project.style_ref_image_paths`

然后按 runtime 顺序把图片拼起来：

- 实际 concat 是 `ref_images = [original_slide] + style_refs`。

接着调用：

- `image_provider.generate_image(prompt, ref_images, aspect_ratio, resolution, thinking_level)`

一个很细但很重要的点：runtime 顺序是 `prompt -> original slide -> style refs`。

`get_restyle_prompt()` 里的 docstring 还写着 style refs 在前、original slide 在后，但那是过时注释。真正该信的是上面的 task assembly，不是 stale comment。

## 4. Request 发起时的 Prompt Template

首轮 prompt 的拼接发生在 `get_restyle_prompt(...)`（签名含可选 `preset_base_body`；未传 custom prompt 时默认正文来自 `style_preset_service` / `assets/presets/ddi/prompt-restyle.md`）。

它有两种模式：

- 没有 custom restyle prompt：将 canonical 预置正文（或传入的 `preset_base_body`）嵌入 IMAGE 角色说明之后
- 有 custom restyle prompt：把用户文本塞进 `Use the following restyle instructions strictly:` 下面（与预置 `prompt-restyle.md` 全文一致时，task 层可走预置路径）

无论哪种模式，prompt 都会强行加一个 hard constraint：所有文本内容必须一字不差。

> **文档与源码**：下方引用的 `prompts.py` 行号/片段可能早于 DDI 预置统一；以仓库内 `get_restyle_prompt` 实现与 `assets/presets/ddi/prompt-restyle.md` 为准。

```bash
nl -ba backend/services/prompts.py | sed -n '781,856p'
```

```output
   781	def get_restyle_prompt(
   782	    page_index: int,
   783	    total_pages: int,
   784	    num_style_refs: int = 1,
   785	    custom_prompt: str = "",
   786	) -> str:
   787	    """
   788	    Generate prompt for single-page restyle.
   789	
   790	    Uses the compose_images pattern: concise English with explicit IMAGE N labels.
   791	    The prompt is sent FIRST in the contents list, followed by images in order:
   792	      IMAGE 1..N = style reference templates
   793	      IMAGE N+1  = original PPT slide (content source)
   794	
   795	    Args:
   796	        page_index: Current page number (1-indexed)
   797	        total_pages: Total number of pages
   798	        num_style_refs: Number of style reference images (default 1)
   799	        custom_prompt: User-provided restyle prompt (optional)
   800	
   801	    Returns:
   802	        Formatted prompt string
   803	    """
   804	    # Build image role labels: original slide first, then style refs
   805	    image_labels = ["IMAGE 1: Original PPT slide (content source)"]
   806	    for i in range(1, num_style_refs + 1):
   807	        img_num = i + 1
   808	        if num_style_refs == 1:
   809	            image_labels.append(f"IMAGE {img_num}: Style reference template")
   810	        else:
   811	            image_labels.append(f"IMAGE {img_num}: Style reference template #{i}")
   812	
   813	    image_section = "\n".join(image_labels)
   814	
   815	    # Page type hint
   816	    page_hint = ""
   817	    if page_index == 1:
   818	        page_hint = " This is a COVER page — use bold, prominent title design."
   819	    elif page_index == total_pages:
   820	        page_hint = " This is an ENDING page — use clean, minimal closing design."
   821	
   822	    custom_prompt_text = (custom_prompt or "").strip()
   823	
   824	    if custom_prompt_text:
   825	        prompt = f"""\
   826	{image_section}
   827	
   828	Use the following restyle instructions strictly:
   829	{custom_prompt_text}
   830	
   831	Non-negotiable: keep ALL text content exactly the same — every word, number, and punctuation mark must be preserved unchanged.
   832	
   833	Page {page_index}/{total_pages}.{page_hint}
   834	
   835	Output: 16:9 landscape PPT slide, high resolution, crisp readable text."""
   836	
   837	        logger.debug(
   838	            f"[get_restyle_prompt] page {page_index}/{total_pages}, "
   839	            f"style_refs={num_style_refs}, custom_prompt=True"
   840	        )
   841	        return prompt
   842	
   843	    prompt = f"""\
   844	{image_section}
   845	
   846	Apply the visual style from IMAGE 2 to IMAGE 1: keep ALL text content exactly the same — every word, number, and punctuation mark must be preserved unchanged. Apply the color scheme, background style, decorative elements, font styling, and layout language from the style reference.
   847	
   848	Page {page_index}/{total_pages}.{page_hint}
   849	
   850	Output: 16:9 landscape PPT slide, high resolution, crisp readable text."""
   851	
   852	    logger.debug(
   853	        f"[get_restyle_prompt] page {page_index}/{total_pages}, "
   854	        f"style_refs={num_style_refs}, custom_prompt=False"
   855	    )
   856	    return prompt
```

### DDI Style 示例 Prompt

下面给一个具体示例：假设用户给的是 DDI style 的 custom instruction，且当前是 12 页 deck 的第 1 页，那么实际发出的 prompt 原文大致长这样。这里故意保留英文，因为这部分就是 request 原文本体。

> IMAGE 1: Original PPT slide (content source)
> IMAGE 2: Style reference template #1
> IMAGE 3: Style reference template #2
>
> Use the following restyle instructions strictly:
> DDI style example:
> - Executive consulting tone, not startup hype
> - White / deep navy / muted cyan palette
> - Strong information hierarchy, generous spacing
> - Use clean geometric dividers, restrained decorative accents
> - Prefer data-storytelling layout patterns over poster-like composition
> - Make the cover feel premium and boardroom-ready
>
> Non-negotiable: keep ALL text content exactly the same — every word, number, and punctuation mark must be preserved unchanged.
>
> Page 1/12. This is a COVER page — use bold, prominent title design.
>
> Output: 16:9 landscape PPT slide, high resolution, crisp readable text.

这个例子不是随便编的，而是严格按上面的 template，用一个合理的 consulting-style `restyle_prompt` 展开出来的。

## 5. 默认 Gemini Provider 与 Model 选择

这个 repo 的 defaults 很关键，因为在任何 page-level 逻辑开始前，它们已经决定了后面会走哪条 request path。

默认配置下：

- `AI_PROVIDER_FORMAT = gemini`
- `TEXT_MODEL = gemini-3-flash-preview`
- `IMAGE_MODEL = gemini-3-pro-image-preview`
- `IMAGE_THINKING_LEVEL = none`

之后 `get_ai_service()` 会缓存 providers，并在多个 requests 之间复用同一个 `AIService` singleton。

```bash
nl -ba backend/config.py | sed -n '48,67p'; printf '\n'; nl -ba backend/config.py | sed -n '80,105p'; printf '\n'; nl -ba backend/services/ai_providers/__init__.py | sed -n '44,68p'; printf '\n'; nl -ba backend/services/ai_providers/__init__.py | sed -n '159,236p'; printf '\n'; nl -ba backend/services/ai_service_manager.py | sed -n '78,130p'
```

```output
    48	    # AI Provider 格式配置: "gemini" (Google GenAI SDK), "openai" (OpenAI SDK), "vertex" (Vertex AI)
    49	    AI_PROVIDER_FORMAT = os.getenv('AI_PROVIDER_FORMAT', 'gemini')
    50	
    51	    # Vertex AI 专用配置（当 AI_PROVIDER_FORMAT=vertex 时使用）
    52	    VERTEX_PROJECT_ID = os.getenv('VERTEX_PROJECT_ID', '')
    53	    VERTEX_LOCATION = os.getenv('VERTEX_LOCATION', 'us-central1')
    54	    
    55	    # GenAI (Gemini) 格式专用配置
    56	    GENAI_TIMEOUT = float(os.getenv('GENAI_TIMEOUT', '300.0'))  # Gemini 超时时间（秒）
    57	    GENAI_MAX_RETRIES = int(os.getenv('GENAI_MAX_RETRIES', '2'))  # Gemini 最大重试次数（应用层实现）
    58	    
    59	    # OpenAI 格式专用配置（当 AI_PROVIDER_FORMAT=openai 时使用）
    60	    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')  # 当 AI_PROVIDER_FORMAT=openai 时必须设置
    61	    OPENAI_API_BASE = os.getenv('OPENAI_API_BASE', 'https://aihubmix.com/v1')
    62	    OPENAI_TIMEOUT = float(os.getenv('OPENAI_TIMEOUT', '300.0'))  # 增加到 5 分钟（生成清洁背景图需要很长时间）
    63	    OPENAI_MAX_RETRIES = int(os.getenv('OPENAI_MAX_RETRIES', '2'))  # 减少重试次数，避免过多重试导致累积超时
    64	    
    65	    # AI 模型配置
    66	    TEXT_MODEL = os.getenv('TEXT_MODEL', 'gemini-3-flash-preview')
    67	    IMAGE_MODEL = os.getenv('IMAGE_MODEL', 'gemini-3-pro-image-preview')

    80	    # 图片生成配置
    81	    DEFAULT_ASPECT_RATIO = os.getenv('DEFAULT_ASPECT_RATIO', '16:9')
    82	    DEFAULT_RESOLUTION = os.getenv('DEFAULT_RESOLUTION', '2K')
    83	    
    84	    # Restyle 编辑上下文图片上限
    85	    RESTYLE_EDIT_MAX_PRUNABLE_IMAGES = int(os.getenv('RESTYLE_EDIT_MAX_PRUNABLE_IMAGES', '6'))
    86	    RESTYLE_EDIT_MAX_TOTAL_IMAGES = int(os.getenv('RESTYLE_EDIT_MAX_TOTAL_IMAGES', '8'))
    87	    DEBUG_RESTYLE_CONTEXT = os.getenv('DEBUG_RESTYLE_CONTEXT', 'false').lower() in ('true', '1', 'yes')
    88	    RESTYLE_EDIT_DEBUG_DIR = os.getenv(
    89	        'RESTYLE_EDIT_DEBUG_DIR',
    90	        os.path.join(PROJECT_ROOT, 'debug', 'restyle-context')
    91	    )
    92	    
    93	    # 日志配置
    94	    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    95	    
    96	    # CORS配置
    97	    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')
    98	    
    99	    # Thinking/推理模式配置
   100	    ENABLE_TEXT_REASONING = os.getenv('ENABLE_TEXT_REASONING', 'false').lower() in ('true', '1', 'yes')
   101	    TEXT_THINKING_BUDGET = int(os.getenv('TEXT_THINKING_BUDGET', '1024'))
   102	    # 图像思考级别 (Gemini 3.1 Flash Image): none, minimal, high
   103	    # See: https://ai.google.dev/gemini-api/docs/image-generation#thinking-process
   104	    IMAGE_THINKING_LEVEL = os.getenv('IMAGE_THINKING_LEVEL', 'none').lower()
   105	    

    44	def get_provider_format() -> str:
    45	    """
    46	    Get the configured AI provider format
    47	
    48	    Priority:
    49	        1. Flask app.config['AI_PROVIDER_FORMAT'] (from database settings)
    50	        2. Environment variable AI_PROVIDER_FORMAT
    51	        3. Default: 'gemini'
    52	
    53	    Returns:
    54	        "gemini", "openai", or "vertex"
    55	    """
    56	    # Try to get from Flask app config first (database settings)
    57	    try:
    58	        from flask import current_app
    59	        if current_app and hasattr(current_app, 'config'):
    60	            config_value = current_app.config.get('AI_PROVIDER_FORMAT')
    61	            if config_value:
    62	                return str(config_value).lower()
    63	    except RuntimeError:
    64	        # Not in Flask application context
    65	        pass
    66	    
    67	    # Fallback to environment variable
    68	    return os.getenv('AI_PROVIDER_FORMAT', 'gemini').lower()

   159	    else:
   160	        # Gemini format (default)
   161	        api_key = _get_config_value('GOOGLE_API_KEY')
   162	        api_base = _get_config_value('GOOGLE_API_BASE')
   163	
   164	        logger.info(f"Provider config - format: gemini, api_base: {api_base}, api_key: {'***' if api_key else 'None'}")
   165	
   166	        if not api_key:
   167	            raise ValueError("GOOGLE_API_KEY (from database settings or environment) is required")
   168	
   169	        return {
   170	            'format': 'gemini',
   171	            'api_key': api_key,
   172	            'api_base': api_base,
   173	        }
   174	
   175	
   176	def get_text_provider(model: str = "gemini-3-flash-preview") -> TextProvider:
   177	    """
   178	    Factory function to get text generation provider based on configuration
   179	
   180	    Args:
   181	        model: Model name to use
   182	
   183	    Returns:
   184	        TextProvider instance (GenAITextProvider or OpenAITextProvider)
   185	    """
   186	    config = _get_provider_config()
   187	    provider_format = config['format']
   188	
   189	    if provider_format == 'openai':
   190	        logger.info(f"Using OpenAI format for text generation, model: {model}")
   191	        return OpenAITextProvider(api_key=config['api_key'], api_base=config['api_base'], model=model)
   192	    elif provider_format == 'vertex':
   193	        logger.info(f"Using Vertex AI for text generation, model: {model}, project: {config['project_id']}")
   194	        return GenAITextProvider(
   195	            model=model,
   196	            vertexai=True,
   197	            project_id=config['project_id'],
   198	            location=config['location']
   199	        )
   200	    else:
   201	        logger.info(f"Using Gemini format for text generation, model: {model}")
   202	        return GenAITextProvider(api_key=config['api_key'], api_base=config['api_base'], model=model)
   203	
   204	
   205	def get_image_provider(model: str = "gemini-3-pro-image-preview") -> ImageProvider:
   206	    """
   207	    Factory function to get image generation provider based on configuration
   208	
   209	    Args:
   210	        model: Model name to use
   211	
   212	    Returns:
   213	        ImageProvider instance (GenAIImageProvider or OpenAIImageProvider)
   214	
   215	    Note:
   216	        OpenAI format does NOT support 4K resolution, only 1K is available.
   217	        If you need higher resolution images, use Gemini or Vertex AI format.
   218	    """
   219	    config = _get_provider_config()
   220	    provider_format = config['format']
   221	
   222	    if provider_format == 'openai':
   223	        logger.info(f"Using OpenAI format for image generation, model: {model}")
   224	        logger.warning("OpenAI format only supports 1K resolution, 4K is not available")
   225	        return OpenAIImageProvider(api_key=config['api_key'], api_base=config['api_base'], model=model)
   226	    elif provider_format == 'vertex':
   227	        logger.info(f"Using Vertex AI for image generation, model: {model}, project: {config['project_id']}")
   228	        return GenAIImageProvider(
   229	            model=model,
   230	            vertexai=True,
   231	            project_id=config['project_id'],
   232	            location=config['location']
   233	        )
   234	    else:
   235	        logger.info(f"Using Gemini format for image generation, model: {model}")
   236	        return GenAIImageProvider(api_key=config['api_key'], api_base=config['api_base'], model=model)

    78	def get_ai_service(force_new: bool = False) -> AIService:
    79	    """
    80	    Get the singleton AIService instance with optimized provider caching
    81	    
    82	    This function creates and returns a singleton AIService instance that reuses
    83	    AI providers (TextProvider and ImageProvider) across requests, significantly
    84	    reducing initialization overhead.
    85	    
    86	    Args:
    87	        force_new: If True, forces creation of a new instance (useful for testing)
    88	        
    89	    Returns:
    90	        AIService singleton instance with cached providers
    91	        
    92	    Note:
    93	        The providers are cached per model name. If TEXT_MODEL or IMAGE_MODEL
    94	        changes in Flask config, new providers will be created automatically.
    95	    """
    96	    global _ai_service_instance
    97	    
    98	    if force_new:
    99	        with _lock:
   100	            logger.info("Force creating new AIService instance")
   101	            _ai_service_instance = None
   102	    
   103	    if _ai_service_instance is None:
   104	        with _lock:
   105	            # Double-check locking pattern
   106	            if _ai_service_instance is None:
   107	                logger.info("Initializing AIService singleton with provider caching")
   108	                
   109	                # Get model names from Flask config or use defaults
   110	                from config import get_config
   111	                config = get_config()
   112	                
   113	                if has_app_context() and current_app and hasattr(current_app, "config"):
   114	                    text_model = current_app.config.get("TEXT_MODEL", config.TEXT_MODEL)
   115	                    image_model = current_app.config.get("IMAGE_MODEL", config.IMAGE_MODEL)
   116	                else:
   117	                    text_model = config.TEXT_MODEL
   118	                    image_model = config.IMAGE_MODEL
   119	                
   120	                # Get cached providers
   121	                text_provider = _get_cached_text_provider(text_model)
   122	                image_provider = _get_cached_image_provider(image_model)
   123	                
   124	                # Create AIService with cached providers
   125	                _ai_service_instance = AIService(
   126	                    text_provider=text_provider,
   127	                    image_provider=image_provider
   128	                )
   129	                
   130	                logger.info(f"AIService singleton created with models: text={text_model}, image={image_model}")
```

## 6. 首轮 Gemini Request 的真实结构

首轮 task 一旦拿到 `prompt` 和 `ref_images`，后面的 request path 就很直白了。

`GenAIImageProvider.generate_image(...)` 会组出：

- `contents = [prompt, original_slide_image, style_ref_1, style_ref_2, ...]`
- `config = GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'], image_config={aspect_ratio, image_size}, optional thinking_config)`
- `client.models.generate_content(model=self.model, contents=contents, config=config)`

所以首轮 Gemini call 不是 multi-turn conversation，而是一个扁平的 mixed list：先放 prompt text，再按 runtime 顺序放图片。

```bash
nl -ba backend/services/ai_providers/image/genai_provider.py | sed -n '117,140p'; printf '\n'; nl -ba backend/services/ai_providers/image/genai_provider.py | sed -n '198,246p'
```

```output
   117	    def _build_generate_config(self, aspect_ratio: str, resolution: str, thinking_level: str) -> 'types.GenerateContentConfig':
   118	        """Build GenerateContentConfig for image generation requests."""
   119	        config_params = {
   120	            'response_modalities': ['TEXT', 'IMAGE'],
   121	            'image_config': types.ImageConfig(
   122	                aspect_ratio=aspect_ratio,
   123	                image_size=resolution
   124	            )
   125	        }
   126	
   127	        # Add thinking config if a valid level is specified
   128	        # Gemini 3.1 Flash Image only supports "minimal" (default) and "high"
   129	        # See: https://ai.google.dev/gemini-api/docs/image-generation#thinking-process
   130	        level_map = {
   131	            'minimal': 'MINIMAL',
   132	            'high': 'HIGH',
   133	        }
   134	        if thinking_level.lower() in level_map:
   135	            config_params['thinking_config'] = types.ThinkingConfig(
   136	                thinking_level=level_map[thinking_level.lower()],
   137	                include_thoughts=True
   138	            )
   139	
   140	        return types.GenerateContentConfig(**config_params)

   198	    def generate_image(
   199	        self,
   200	        prompt: str,
   201	        ref_images: Optional[List[Image.Image]] = None,
   202	        aspect_ratio: str = "16:9",
   203	        resolution: str = "2K",
   204	        thinking_level: str = "none"
   205	    ) -> Optional[Image.Image]:
   206	        """
   207	        Generate image using Google GenAI SDK
   208	        
   209	        Args:
   210	            prompt: The image generation prompt
   211	            ref_images: Optional list of reference images
   212	            aspect_ratio: Image aspect ratio
   213	            resolution: Image resolution (supports "1K", "2K", "4K")
   214	            thinking_level: Thinking level for Gemini 3 ("none", "minimal", "high")
   215	            
   216	        Returns:
   217	            Generated PIL Image object, or None if failed
   218	        """
   219	        try:
   220	            # Build contents list: prompt FIRST, then reference images
   221	            # This order significantly improves instruction-following for Gemini
   222	            # (validated against compose_images.py pattern from gemini-imagegen skill)
   223	            contents = [prompt]
   224	            
   225	            # Add reference images after prompt
   226	            if ref_images:
   227	                for ref_img in ref_images:
   228	                    contents.append(ref_img)
   229	            
   230	            ref_count = len(ref_images) if ref_images else 0
   231	            ref_details = ", ".join(f"{img.size[0]}x{img.size[1]}" for img in ref_images) if ref_images else "none"
   232	            prompt_preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
   233	            logger.info(f"🌐 GenAI image request: model={self.model}, "
   234	                        f"ref_images={ref_count} [{ref_details}], "
   235	                        f"aspect_ratio={aspect_ratio}, resolution={resolution}, thinking_level={thinking_level}")
   236	            logger.info(f"📝 Prompt ({len(prompt)} chars): {prompt_preview}")
   237	            
   238	            config = self._build_generate_config(aspect_ratio, resolution, thinking_level)
   239	
   240	            response = self.client.models.generate_content(
   241	                model=self.model,
   242	                contents=contents,
   243	                config=config
   244	            )
   245	            
   246	            return self._extract_last_image(response)
```

## 7. 编辑轮 Edit Round 是另一条 Pipeline

一旦首张图已经生成，后续 image edit 就不再复用首轮那种 flat request。

这个 edit endpoint 接受新的 `edit_instruction`，外加可选的 extra context images。如果这个 project 是 `restyle` 类型，background task 就会切到一条 context-aware pipeline，而不是 legacy 的单 prompt edit path。

```bash
nl -ba backend/controllers/page_controller.py | sed -n '515,675p'
```

```output
   515	@page_bp.route('/<project_id>/pages/<page_id>/edit/image', methods=['POST'])
   516	def edit_page_image(project_id, page_id):
   517	    """
   518	    POST /api/projects/{project_id}/pages/{page_id}/edit/image - Edit page image
   519	    
   520	    Request body (JSON or multipart/form-data):
   521	    {
   522	        "edit_instruction": "更改文本框样式为虚线",
   523	        "context_images": {
   524	            "use_template": true,  // 是否使用template图片
   525	            "desc_image_urls": ["url1", "url2"],  // desc中的图片URL列表
   526	            "uploaded_image_ids": ["file1", "file2"]  // 上传的图片文件ID列表（在multipart中）
   527	        }
   528	    }
   529	    
   530	    For multipart/form-data:
   531	    - edit_instruction: text field
   532	    - use_template: text field (true/false)
   533	    - desc_image_urls: JSON array string
   534	    - context_images: file uploads (multiple files with key "context_images")
   535	    """
   536	    try:
   537	        page = _get_owned_page(project_id, page_id)
   538	        
   539	        if not page or page.project_id != project_id:
   540	            return not_found('Page')
   541	        
   542	        if not page.generated_image_path:
   543	            return bad_request("Page must have generated image first")
   544	        
   545	        project = _get_owned_project(project_id)
   546	        if not project:
   547	            return not_found('Project')
   548	        
   549	        # Initialize services
   550	        ai_service = get_ai_service()
   551	        
   552	        file_service = FileService(current_app.config['UPLOAD_FOLDER'])
   553	        
   554	        # Parse request data (support both JSON and multipart/form-data)
   555	        if request.is_json:
   556	            data = request.get_json()
   557	            uploaded_files = []
   558	        else:
   559	            # multipart/form-data
   560	            data = request.form.to_dict()
   561	            # Get uploaded files
   562	            uploaded_files = request.files.getlist('context_images')
   563	            # Parse JSON fields
   564	            if 'desc_image_urls' in data and data['desc_image_urls']:
   565	                try:
   566	                    data['desc_image_urls'] = json.loads(data['desc_image_urls'])
   567	                except:
   568	                    data['desc_image_urls'] = []
   569	            else:
   570	                data['desc_image_urls'] = []
   571	        
   572	        if not data or 'edit_instruction' not in data:
   573	            return bad_request("edit_instruction is required")
   574	        
   575	        # Get current image path
   576	        current_image_path = file_service.get_absolute_path(page.generated_image_path)
   577	        
   578	        # Get original description if available
   579	        original_description = None
   580	        desc_content = page.get_description_content()
   581	        if desc_content:
   582	            # Extract text from description_content
   583	            original_description = desc_content.get('text') or ''
   584	            # If text is not available, try to construct from text_content
   585	            if not original_description and desc_content.get('text_content'):
   586	                if isinstance(desc_content['text_content'], list):
   587	                    original_description = '\n'.join(desc_content['text_content'])
   588	                else:
   589	                    original_description = str(desc_content['text_content'])
   590	        
   591	        # Collect additional reference images
   592	        additional_ref_images = []
   593	        
   594	        # 1. Add template image if requested
   595	        context_images = data.get('context_images', {})
   596	        if isinstance(context_images, dict):
   597	            use_template = context_images.get('use_template', False)
   598	        else:
   599	            use_template = data.get('use_template', 'false').lower() == 'true'
   600	        
   601	        if use_template:
   602	            template_path = file_service.get_template_path(project_id)
   603	            if template_path:
   604	                additional_ref_images.append(template_path)
   605	        
   606	        # 2. Add desc image URLs if provided
   607	        if isinstance(context_images, dict):
   608	            desc_image_urls = context_images.get('desc_image_urls', [])
   609	        else:
   610	            desc_image_urls = data.get('desc_image_urls', [])
   611	        
   612	        if desc_image_urls:
   613	            if isinstance(desc_image_urls, str):
   614	                try:
   615	                    desc_image_urls = json.loads(desc_image_urls)
   616	                except:
   617	                    desc_image_urls = []
   618	            if isinstance(desc_image_urls, list):
   619	                additional_ref_images.extend(desc_image_urls)
   620	        
   621	        # 3. Save and add uploaded files to a persistent location
   622	        temp_dir = None
   623	        if uploaded_files:
   624	            # Create a temporary directory in the project's upload folder
   625	            import tempfile
   626	            import shutil
   627	            from werkzeug.utils import secure_filename
   628	            temp_dir = Path(tempfile.mkdtemp(dir=current_app.config['UPLOAD_FOLDER']))
   629	            try:
   630	                for uploaded_file in uploaded_files:
   631	                    if uploaded_file.filename:
   632	                        # Save to temp directory
   633	                        temp_path = temp_dir / secure_filename(uploaded_file.filename)
   634	                        uploaded_file.save(str(temp_path))
   635	                        additional_ref_images.append(str(temp_path))
   636	            except Exception as e:
   637	                # Clean up temp directory on error
   638	                if temp_dir and temp_dir.exists():
   639	                    shutil.rmtree(temp_dir)
   640	                raise e
   641	        
   642	        # Create async task for image editing
   643	        task = Task(
   644	            project_id=project_id,
   645	            owner_id=get_current_user_id(),
   646	            task_type='EDIT_PAGE_IMAGE',
   647	            status='PENDING'
   648	        )
   649	        task.set_progress({
   650	            'total': 1,
   651	            'completed': 0,
   652	            'failed': 0
   653	        })
   654	        db.session.add(task)
   655	        db.session.commit()
   656	        
   657	        # Get app instance for background task
   658	        app = current_app._get_current_object()
   659	        
   660	        # Submit background task
   661	        task_manager.submit_task(
   662	            task.id,
   663	            edit_page_image_task,
   664	            project_id,
   665	            page_id,
   666	            data['edit_instruction'],
   667	            ai_service,
   668	            file_service,
   669	            current_app.config['DEFAULT_ASPECT_RATIO'],
   670	            current_app.config['DEFAULT_RESOLUTION'],
   671	            original_description,
   672	            additional_ref_images if additional_ref_images else None,
   673	            str(temp_dir) if temp_dir else None,
   674	            app
   675	        )
```

```bash
nl -ba backend/services/task_manager.py | sed -n '679,795p'
```

```output
   679	            is_restyle_project = False
   680	            trace = None
   681	            try:
   682	                # Check if this is a restyle project
   683	                from models import Project
   684	                project = Project.query.get(project_id)
   685	                
   686	                if project and project.creation_type == 'restyle':
   687	                    is_restyle_project = True
   688	                    # Use conversation context for restyle edits
   689	                    from services.restyle_edit_context import (
   690	                        build_restyle_edit_context,
   691	                        MissingStructuralImagesError,
   692	                        ContextImageLimitExceeded,
   693	                    )
   694	                    from services.restyle_edit_debug import (
   695	                        enrich_image_manifest,
   696	                        log_restyle_edit_event,
   697	                        maybe_write_debug_artifact,
   698	                    )
   699	                    from config import get_config
   700	                    config = get_config()
   701	                    current_version = PageImageVersion.query.filter_by(
   702	                        page_id=page_id,
   703	                        is_current=True,
   704	                    ).first()
   705	                    trace = {
   706	                        'task_id': task_id,
   707	                        'project_id': project_id,
   708	                        'page_id': page_id,
   709	                        'flow_kind': 'edit_restyle',
   710	                        'page_order_index': page.order_index + 1,
   711	                        'source_version_number': current_version.version_number if current_version else None,
   712	                        'page_version_number': None,
   713	                    }
   714	                    
   715	                    # Validate structural image availability (DB path → abs → readable)
   716	                    original_slide_abs = None
   717	                    if page.original_slide_image_path:
   718	                        candidate = file_service.get_absolute_path(
   719	                            page.original_slide_image_path
   720	                        )
   721	                        if os.path.exists(candidate):
   722	                            original_slide_abs = candidate
   723	                        else:
   724	                            logger.warning(f"Original slide file missing on disk: {candidate}")
   725	                    
   726	                    current_abs = current_image_path if os.path.exists(current_image_path) else None
   727	                    if not current_abs:
   728	                        logger.warning(f"Current selected image missing on disk: {current_image_path}")
   729	                    
   730	                    # Validate style ref availability
   731	                    style_ref_abs_paths = []
   732	                    for ref_path in (project.get_style_ref_image_paths() or []):
   733	                        abs_path = file_service.get_absolute_path(ref_path)
   734	                        if os.path.exists(abs_path):
   735	                            style_ref_abs_paths.append(abs_path)
   736	                        else:
   737	                            logger.warning(f"Style ref file missing on disk: {abs_path}")
   738	                    
   739	                    # Normalize extra ref paths (may be /files/..., abs paths, or temp uploads)
   740	                    normalized_extras = None
   741	                    if additional_ref_images:
   742	                        normalized_extras = []
   743	                        upload_folder = file_service.upload_folder if hasattr(file_service, 'upload_folder') else ''
   744	                        for ref in additional_ref_images:
   745	                            if os.path.exists(ref):
   746	                                normalized_extras.append(ref)
   747	                            elif ref.startswith('/files/') and upload_folder:
   748	                                relative = ref[len('/files/'):].lstrip('/')
   749	                                local = os.path.abspath(os.path.join(upload_folder, relative))
   750	                                if os.path.exists(local):
   751	                                    normalized_extras.append(local)
   752	                                else:
   753	                                    logger.warning(f"Extra ref not found after /files/ resolve: {ref}")
   754	                            else:
   755	                                logger.warning(f"Skipping unresolvable extra ref in restyle edit: {ref}")
   756	                    
   757	                    total_pages_count = Page.query.filter_by(
   758	                        project_id=project_id
   759	                    ).count()
   760	                    
   761	                    try:
   762	                        ctx = build_restyle_edit_context(
   763	                            original_slide_path=original_slide_abs,
   764	                            style_ref_paths=style_ref_abs_paths,
   765	                            restyle_base_prompt_snapshot=page.restyle_base_prompt_snapshot,
   766	                            restyle_prompt=project.restyle_prompt or '',
   767	                            current_selected_path=current_abs,
   768	                            edit_instruction=edit_instruction,
   769	                            current_extra_ref_paths=normalized_extras,
   770	                            page_index=page.order_index + 1,
   771	                            total_pages=total_pages_count,
   772	                            prunable_cap=config.RESTYLE_EDIT_MAX_PRUNABLE_IMAGES,
   773	                            total_cap=config.RESTYLE_EDIT_MAX_TOTAL_IMAGES,
   774	                        )
   775	                        context_event = {
   776	                            'snapshot_source': ctx.snapshot_source,
   777	                            'degraded_context': ctx.degraded_context,
   778	                            'baseline_images_count': ctx.baseline_images_count,
   779	                            'current_images_count': ctx.current_images_count,
   780	                            'turns_summary': ctx.turns_summary,
   781	                            'image_manifest': enrich_image_manifest(ctx.image_manifest),
   782	                        }
   783	                        log_restyle_edit_event('restyle_edit_context_built', trace, context_event)
   784	                        maybe_write_debug_artifact(
   785	                            config,
   786	                            event_name='context_built',
   787	                            trace=trace,
   788	                            payload=context_event,
   789	                            degraded_context=ctx.degraded_context,
   790	                        )
   791	                        image = ai_service.edit_restyle_image_with_context(
   792	                            ctx, aspect_ratio, resolution, trace_context=trace
   793	                        )
   794	                    except (MissingStructuralImagesError, ContextImageLimitExceeded) as e:
   795	                        raise ValueError(f"Restyle edit context error: {e}")
```

## 8. Edit Context 是怎么组出来的

这条 edit pipeline 解决的是一个比首轮生成更难的问题。

它必须同时保住：

- original slide structure
- original style references
- 精确的 first-pass prompt snapshot
- 当前选中的 generated version
- 新的 delta instruction
- 当前 edit request 带进来的 optional extra references

因此它不会一上来就把所有东西拍平成一个 prompt，而是先构造一个 provider-agnostic 的 conversation context。

```bash
nl -ba backend/services/restyle_edit_context.py | sed -n '219,399p'
```

```output
   219	_STYLE_LOCK = (
   220	    "STYLE LOCK: You must maintain visual consistency with the original style "
   221	    "throughout all modifications. Preserve the color scheme, typography, "
   222	    "decorative elements, and layout language from the baseline."
   223	)
   224	
   225	
   226	def _build_conversation_contents(
   227	    *,
   228	    baseline_text: str,
   229	    original_slide_path: Optional[str],
   230	    selected_style_refs: List[str],
   231	    current_selected_path: Optional[str],
   232	    edit_instruction: str,
   233	    selected_extras: List[str],
   234	) -> list:
   235	    """Build provider-agnostic multi-turn conversation contents."""
   236	    turns: list = []
   237	
   238	    # Turn 1 (user, text): baseline instruction block
   239	    turns.append({
   240	        'role': 'user',
   241	        'parts': [{'text': baseline_text}],
   242	    })
   243	
   244	    # Turn 2 (user, images): baseline images
   245	    turn2_parts: list = []
   246	    if original_slide_path:
   247	        turn2_parts.append({'image_path': original_slide_path})
   248	    for ref in selected_style_refs:
   249	        turn2_parts.append({'image_path': ref})
   250	    if turn2_parts:
   251	        turns.append({'role': 'user', 'parts': turn2_parts})
   252	
   253	    # Turn 3 (user, image): current selected slide version.
   254	    # This is user-supplied context, not a prior SDK model response. Using a
   255	    # synthetic model turn with Gemini 3 image models triggers thought-signature
   256	    # validation, because only real model outputs carry those signatures.
   257	    if current_selected_path:
   258	        turns.append({
   259	            'role': 'user',
   260	            'parts': [{'image_path': current_selected_path}],
   261	        })
   262	
   263	    # Turn 4 (user, text + optional images): current delta instruction
   264	    turn4_parts: list = [{'text': edit_instruction}]
   265	    for extra in selected_extras:
   266	        turn4_parts.append({'image_path': extra})
   267	    turns.append({'role': 'user', 'parts': turn4_parts})
   268	
   269	    return turns
   270	
   271	
   272	# ── Legacy fallback builder ───────────────────────────────────
   273	
   274	
   275	def _build_legacy_prompt(
   276	    baseline_text: str,
   277	    edit_instruction: str,
   278	) -> str:
   279	    """Merge baseline + current text into single prompt for legacy providers."""
   280	    return f"{baseline_text}\n\n---\n\nEdit instruction: {edit_instruction}"
   281	
   282	
   283	def _build_legacy_ref_images(
   284	    *,
   285	    original_slide_path: Optional[str],
   286	    selected_style_refs: List[str],
   287	    current_selected_path: Optional[str],
   288	    selected_extras: List[str],
   289	) -> List[str]:
   290	    """Flatten images in deterministic order for legacy providers."""
   291	    images: List[str] = []
   292	    if original_slide_path:
   293	        images.append(original_slide_path)
   294	    images.extend(selected_style_refs)
   295	    if current_selected_path:
   296	        images.append(current_selected_path)
   297	    images.extend(selected_extras)
   298	    return images
   299	
   300	
   301	# ── Main entry point ──────────────────────────────────────────
   302	
   303	
   304	def build_restyle_edit_context(
   305	    *,
   306	    original_slide_path: Optional[str],
   307	    style_ref_paths: List[str],
   308	    restyle_base_prompt_snapshot: Optional[str],
   309	    restyle_prompt: str,
   310	    current_selected_path: Optional[str],
   311	    edit_instruction: str,
   312	    current_extra_ref_paths: Optional[List[str]] = None,
   313	    page_index: int = 1,
   314	    total_pages: int = 1,
   315	    prunable_cap: int = 6,
   316	    total_cap: int = 8,
   317	) -> RestyleEditContext:
   318	    """
   319	    Build restyle edit context from immutable baseline + mutable current buckets.
   320	
   321	    Raises:
   322	        MissingStructuralImagesError: both structural source images unavailable.
   323	        ContextImageLimitExceeded: assembled set exceeds total cap after pruning.
   324	    """
   325	    extras = current_extra_ref_paths or []
   326	    degraded = False
   327	    snapshot_source = 'persisted'
   328	
   329	    # Snapshot resolution
   330	    snapshot = restyle_base_prompt_snapshot
   331	    if not snapshot:
   332	        snapshot = reconstruct_base_prompt_snapshot(
   333	            page_index=page_index,
   334	            total_pages=total_pages,
   335	            num_style_refs=len(style_ref_paths),
   336	            custom_prompt=restyle_prompt,
   337	        )
   338	        degraded = True
   339	        snapshot_source = 'reconstructed'
   340	        logger.info("restyle_edit_context: snapshot missing, using reconstruction",
   341	                     extra={'degraded_context': True})
   342	
   343	    # Degrade if structural images partially missing
   344	    if not original_slide_path or not current_selected_path:
   345	        degraded = True
   346	
   347	    # Degrade if style refs missing
   348	    if not style_ref_paths:
   349	        degraded = True
   350	
   351	    # Image selection + pruning
   352	    anchors, selected_style_refs, selected_extras, baseline_count, current_count, image_manifest = (
   353	        _select_images(
   354	            original_slide_path=original_slide_path,
   355	            style_ref_paths=style_ref_paths,
   356	            current_selected_path=current_selected_path,
   357	            current_extra_ref_paths=extras,
   358	            prunable_cap=prunable_cap,
   359	            total_cap=total_cap,
   360	        )
   361	    )
   362	
   363	    # Assemble baseline text block
   364	    parts = [_STYLE_LOCK]
   365	    if restyle_prompt:
   366	        parts.append(f"Project restyle instruction: {restyle_prompt}")
   367	    parts.append(f"Original generation prompt:\n{snapshot}")
   368	    baseline_text = "\n\n".join(parts)
   369	
   370	    # Build conversation contents
   371	    conversation = _build_conversation_contents(
   372	        baseline_text=baseline_text,
   373	        original_slide_path=original_slide_path,
   374	        selected_style_refs=selected_style_refs,
   375	        current_selected_path=current_selected_path,
   376	        edit_instruction=edit_instruction,
   377	        selected_extras=selected_extras,
   378	    )
   379	
   380	    # Build legacy fallback
   381	    legacy_prompt = _build_legacy_prompt(baseline_text, edit_instruction)
   382	    legacy_images = _build_legacy_ref_images(
   383	        original_slide_path=original_slide_path,
   384	        selected_style_refs=selected_style_refs,
   385	        current_selected_path=current_selected_path,
   386	        selected_extras=selected_extras,
   387	    )
   388	    turns_summary = _build_turns_summary(conversation)
   389	
   390	    return RestyleEditContext(
   391	        conversation_contents=conversation,
   392	        legacy_prompt=legacy_prompt,
   393	        legacy_ref_images=legacy_images,
   394	        degraded_context=degraded,
   395	        baseline_images_count=baseline_count,
   396	        current_images_count=current_count,
   397	        snapshot_source=snapshot_source,
   398	        turns_summary=turns_summary,
   399	        image_manifest=image_manifest,
```

### SDK Serialization 前的 Provider-Agnostic Edit Payload

这一段的 mental model 最值得记住：

1. Turn 1，user text：`STYLE LOCK + project restyle instruction + original generation prompt snapshot`
2. Turn 2，user images：`original slide + selected style refs`
3. Turn 3，user image：`current selected generated slide version`
4. Turn 4，user text 加 optional images：`fresh edit instruction + extra current-round references`

这里有两个设计点很聪明：

- 复用了 first-pass prompt snapshot，所以 edit round 能持续锚定原始 styling intent
- 当前选中图仍然作为 `user` turn 发送，而不是伪造 `model` turn，因为 Gemini image models 会对 synthetic model turn 做 thought signature 校验

## 9. AIService 的决策：先 Conversation，后 Legacy Fallback

`AIService.edit_restyle_image_with_context(...)` 会决定 image provider 能不能直接吃 conversation contents。

对 Gemini 来说答案是可以，所以它会先试 conversation mode。如果 Gemini 因为某种 retryable 的 schema / payload 问题拒绝这次请求，代码会回退一次，改走 flatten 后的 legacy prompt+images call。

```bash
nl -ba backend/services/ai_service.py | sed -n '563,755p'
```

```output
   563	    def edit_restyle_image_with_context(self, context, aspect_ratio='16:9', resolution='2K', trace_context=None):
   564	        """
   565	        Edit restyle image using conversation context with single fallback.
   566	        
   567	        Args:
   568	            context: RestyleEditContext from build_restyle_edit_context()
   569	            aspect_ratio: Image aspect ratio
   570	            resolution: Image resolution
   571	        
   572	        Returns:
   573	            PIL Image or raises
   574	        """
   575	        from config import get_config
   576	        from .restyle_edit_context import is_retryable_conversation_error
   577	        from .restyle_edit_debug import (
   578	            enrich_image_manifest,
   579	            log_restyle_edit_event,
   580	            maybe_write_debug_artifact,
   581	            serialize_conversation_contents,
   582	        )
   583	
   584	        config = get_config()
   585	        trace = trace_context or {}
   586	        conversation_attempted = False
   587	        provider_fallback = False
   588	        conversation_supported = getattr(self.image_provider, 'supports_conversation_contents', False)
   589	        snapshot_present = context.snapshot_source == 'persisted'
   590	        provider_name = type(self.image_provider).__name__
   591	        provider_model = getattr(self.image_provider, 'model', None)
   592	        decision_event = {
   593	            'conversation_supported': conversation_supported,
   594	            'snapshot_present': snapshot_present,
   595	            'degraded_context': context.degraded_context,
   596	            'provider': provider_name,
   597	            'model': provider_model,
   598	        }
   599	        log_restyle_edit_event('restyle_edit_provider_decision', trace, decision_event)
   600	        maybe_write_debug_artifact(
   601	            config,
   602	            event_name='provider_decision',
   603	            trace=trace,
   604	            payload=decision_event,
   605	            degraded_context=context.degraded_context,
   606	        )
   607	        
   608	        if conversation_supported:
   609	            conversation_attempted = True
   610	            conversation_request_event = {
   611	                'context_mode': 'restyle_conversation',
   612	                'turns_summary': context.turns_summary,
   613	                'snapshot_source': context.snapshot_source,
   614	                'image_manifest': enrich_image_manifest(context.image_manifest),
   615	                'conversation_contents': serialize_conversation_contents(context.conversation_contents),
   616	            }
   617	            log_restyle_edit_event('restyle_edit_provider_request', trace, {
   618	                'context_mode': 'restyle_conversation',
   619	                'turns_summary': context.turns_summary,
   620	                'snapshot_source': context.snapshot_source,
   621	            })
   622	            maybe_write_debug_artifact(
   623	                config,
   624	                event_name='provider_request',
   625	                trace=trace,
   626	                payload=conversation_request_event,
   627	                degraded_context=context.degraded_context,
   628	            )
   629	            try:
   630	                resolved_contents = self._resolve_conversation_images(context.conversation_contents)
   631	                result = self.image_provider.generate_image_from_conversation(
   632	                    contents=resolved_contents,
   633	                    aspect_ratio=aspect_ratio,
   634	                    resolution=resolution,
   635	                    thinking_level=self._get_image_thinking_level()
   636	                )
   637	                if result:
   638	                    result_event = {
   639	                        'context_mode': 'restyle_conversation',
   640	                        'conversation_attempted': True,
   641	                        'provider_fallback': False,
   642	                        'degraded_context': context.degraded_context,
   643	                        'baseline_images_count': context.baseline_images_count,
   644	                        'current_images_count': context.current_images_count,
   645	                        'snapshot_present': snapshot_present,
   646	                        'provider': provider_name,
   647	                        'model': provider_model,
   648	                    }
   649	                    log_restyle_edit_event('restyle_edit_provider_result', trace, result_event)
   650	                    maybe_write_debug_artifact(
   651	                        config,
   652	                        event_name='provider_result',
   653	                        trace=trace,
   654	                        payload=result_event,
   655	                        degraded_context=context.degraded_context,
   656	                    )
   657	                    return result
   658	            except Exception as e:
   659	                if is_retryable_conversation_error(e):
   660	                    logger.warning(f"Conversation mode failed with retryable error, falling back to legacy: {e}")
   661	                    provider_fallback = True
   662	                    fallback_event = {
   663	                        'from_mode': 'restyle_conversation',
   664	                        'to_mode': 'legacy_flattened',
   665	                        'provider_fallback': True,
   666	                        'classified_retryable': True,
   667	                        'error_message': str(e),
   668	                        'provider': provider_name,
   669	                        'model': provider_model,
   670	                    }
   671	                    log_restyle_edit_event('restyle_edit_provider_fallback', trace, fallback_event)
   672	                    maybe_write_debug_artifact(
   673	                        config,
   674	                        event_name='provider_fallback',
   675	                        trace=trace,
   676	                        payload=fallback_event,
   677	                        provider_fallback=True,
   678	                        error=True,
   679	                    )
   680	                else:
   681	                    error_event = {
   682	                        'context_mode': 'restyle_conversation',
   683	                        'provider_fallback': False,
   684	                        'classified_retryable': False,
   685	                        'error_message': str(e),
   686	                        'provider': provider_name,
   687	                        'model': provider_model,
   688	                    }
   689	                    log_restyle_edit_event('restyle_edit_provider_result', trace, error_event)
   690	                    maybe_write_debug_artifact(
   691	                        config,
   692	                        event_name='provider_result',
   693	                        trace=trace,
   694	                        payload=error_event,
   695	                        error=True,
   696	                    )
   697	                    raise
   698	        
   699	        # Legacy fallback path
   700	        legacy_request_event = {
   701	            'context_mode': 'legacy_flattened',
   702	            'conversation_attempted': conversation_attempted,
   703	            'provider_fallback': provider_fallback,
   704	            'snapshot_source': context.snapshot_source,
   705	            'prompt': context.legacy_prompt,
   706	            'prompt_len': len(context.legacy_prompt),
   707	            'legacy_ref_images': context.legacy_ref_images,
   708	            'image_manifest': enrich_image_manifest(context.image_manifest),
   709	        }
   710	        log_restyle_edit_event('restyle_edit_provider_request', trace, {
   711	            'context_mode': 'legacy_flattened',
   712	            'conversation_attempted': conversation_attempted,
   713	            'provider_fallback': provider_fallback,
   714	            'prompt_len': len(context.legacy_prompt),
   715	            'ref_image_count': len(context.legacy_ref_images),
   716	        })
   717	        maybe_write_debug_artifact(
   718	            config,
   719	            event_name='provider_request',
   720	            trace=trace,
   721	            payload=legacy_request_event,
   722	            degraded_context=context.degraded_context,
   723	            provider_fallback=provider_fallback,
   724	        )
   725	        ref_images = self._resolve_ref_image_paths(context.legacy_ref_images)
   726	        result = self.image_provider.generate_image(
   727	            prompt=context.legacy_prompt,
   728	            ref_images=ref_images if ref_images else None,
   729	            aspect_ratio=aspect_ratio,
   730	            resolution=resolution,
   731	            thinking_level=self._get_image_thinking_level()
   732	        )
   733	
   734	        result_event = {
   735	            'context_mode': 'legacy_flattened',
   736	            'conversation_attempted': conversation_attempted,
   737	            'provider_fallback': provider_fallback,
   738	            'degraded_context': context.degraded_context,
   739	            'baseline_images_count': context.baseline_images_count,
   740	            'current_images_count': context.current_images_count,
   741	            'snapshot_present': snapshot_present,
   742	            'provider': provider_name,
   743	            'model': provider_model,
   744	        }
   745	        log_restyle_edit_event('restyle_edit_provider_result', trace, result_event)
   746	        maybe_write_debug_artifact(
   747	            config,
   748	            event_name='provider_result',
   749	            trace=trace,
   750	            payload=result_event,
   751	            degraded_context=context.degraded_context,
   752	            provider_fallback=provider_fallback,
   753	        )
   754	        
   755	        return result
```

## 10. Gemini Conversation Request 的真实结构

当 provider 是 Gemini 时，edit path 会先把 image paths 解析成 PIL images，再把每个 conversation turn 转成 Google GenAI SDK 的 `Content` objects，最后才调用 `client.models.generate_content(...)`。

所以 edit request 的结构更接近下面这样：

- `contents[0] = UserContent(parts=[Part.from_text(baseline_text)])`
- `contents[1] = UserContent(parts=[Part.from_bytes(original_slide), Part.from_bytes(style_ref_1), ...])`
- `contents[2] = UserContent(parts=[Part.from_bytes(current_selected_version)])`
- `contents[3] = UserContent(parts=[Part.from_text(edit_instruction), Part.from_bytes(extra_ref_1), ...])`
- `config = GenerateContentConfig(...)`
- `client.models.generate_content(model=self.model, contents=contents, config=config)`

这就是它和首轮 restyle 的本质区别：first pass 用 flat mixed list，edit pass 用 multi-turn typed `Content` objects。

```bash
nl -ba backend/services/ai_providers/image/genai_provider.py | sed -n '71,140p'; printf '\n'; nl -ba backend/services/ai_providers/image/genai_provider.py | sed -n '253,292p'; printf '\n'; nl -ba backend/tests/unit/test_genai_image_provider_conversation.py | sed -n '40,80p'
```

```output
    71	    @staticmethod
    72	    def _image_to_part(image: Image.Image) -> 'types.Part':
    73	        """Serialize a PIL image into the inline-data format expected by the SDK."""
    74	        image_bytes = BytesIO()
    75	        image_format = (image.format or 'PNG').upper()
    76	        image.save(image_bytes, format=image_format)
    77	        mime_type = {
    78	            'PNG': 'image/png',
    79	            'JPEG': 'image/jpeg',
    80	            'JPG': 'image/jpeg',
    81	            'WEBP': 'image/webp',
    82	            'GIF': 'image/gif',
    83	        }.get(image_format, 'image/png')
    84	        return types.Part.from_bytes(data=image_bytes.getvalue(), mime_type=mime_type)
    85	
    86	    def _conversation_part_to_sdk(self, part) -> 'types.Part':
    87	        """Convert a provider-agnostic conversation part into an SDK Part."""
    88	        if isinstance(part, types.Part):
    89	            return part
    90	        if isinstance(part, str):
    91	            return types.Part.from_text(text=part)
    92	        if isinstance(part, Image.Image):
    93	            return self._image_to_part(part)
    94	        if isinstance(part, dict):
    95	            if 'text' in part:
    96	                return types.Part.from_text(text=part['text'])
    97	            if 'image' in part and isinstance(part['image'], Image.Image):
    98	                return self._image_to_part(part['image'])
    99	
   100	        raise ValueError(f"Unsupported conversation part type: {type(part)}")
   101	
   102	    def _conversation_turn_to_sdk(self, turn) -> 'types.Content':
   103	        """Convert a provider-agnostic turn dict into SDK typed content."""
   104	        role = turn.get('role', 'user')
   105	        sdk_parts = [self._conversation_part_to_sdk(part) for part in turn.get('parts', [])]
   106	
   107	        if role == 'user':
   108	            return types.UserContent(parts=sdk_parts)
   109	        if role == 'model':
   110	            return types.ModelContent(parts=sdk_parts)
   111	        return types.Content(role=role, parts=sdk_parts)
   112	
   113	    def _serialize_conversation_contents(self, contents: list) -> list:
   114	        """Convert conversation contents into the typed structure required by google-genai."""
   115	        return [self._conversation_turn_to_sdk(turn) for turn in contents]
   116	
   117	    def _build_generate_config(self, aspect_ratio: str, resolution: str, thinking_level: str) -> 'types.GenerateContentConfig':
   118	        """Build GenerateContentConfig for image generation requests."""
   119	        config_params = {
   120	            'response_modalities': ['TEXT', 'IMAGE'],
   121	            'image_config': types.ImageConfig(
   122	                aspect_ratio=aspect_ratio,
   123	                image_size=resolution
   124	            )
   125	        }
   126	
   127	        # Add thinking config if a valid level is specified
   128	        # Gemini 3.1 Flash Image only supports "minimal" (default) and "high"
   129	        # See: https://ai.google.dev/gemini-api/docs/image-generation#thinking-process
   130	        level_map = {
   131	            'minimal': 'MINIMAL',
   132	            'high': 'HIGH',
   133	        }
   134	        if thinking_level.lower() in level_map:
   135	            config_params['thinking_config'] = types.ThinkingConfig(
   136	                thinking_level=level_map[thinking_level.lower()],
   137	                include_thoughts=True
   138	            )
   139	
   140	        return types.GenerateContentConfig(**config_params)

   253	    def generate_image_from_conversation(
   254	        self,
   255	        contents: list,
   256	        aspect_ratio: str = "16:9",
   257	        resolution: str = "2K",
   258	        thinking_level: str = "none"
   259	    ) -> Optional[Image.Image]:
   260	        """
   261	        Generate image from multi-turn conversation contents.
   262	        
   263	        Used for restyle edit requests where baseline context and current delta
   264	        are encoded as separate conversation turns.
   265	        
   266	        Note: No @retry decorator — retry is managed at the caller level
   267	        for conversation mode (with fallback to legacy path).
   268	        
   269	        Args:
   270	            contents: Multi-turn conversation contents for Gemini API
   271	            aspect_ratio: Image aspect ratio
   272	            resolution: Image resolution
   273	            thinking_level: Thinking level for supported models
   274	            
   275	        Returns:
   276	            Generated PIL Image object, or None if failed
   277	        """
   278	        try:
   279	            logger.info(f"🌐 GenAI conversation request: model={self.model}, "
   280	                        f"turns={len(contents)}, "
   281	                        f"aspect_ratio={aspect_ratio}, resolution={resolution}, thinking_level={thinking_level}")
   282	
   283	            config = self._build_generate_config(aspect_ratio, resolution, thinking_level)
   284	            sdk_contents = self._serialize_conversation_contents(contents)
   285	
   286	            response = self.client.models.generate_content(
   287	                model=self.model,
   288	                contents=sdk_contents,
   289	                config=config
   290	            )
   291	
   292	            return self._extract_last_image(response)

    40	    def test_generate_image_from_conversation_calls_generate_content(self):
    41	        """Should serialize conversation contents into SDK typed content objects."""
    42	        with patch('services.ai_providers.image.genai_provider.genai'):
    43	            from services.ai_providers.image.genai_provider import GenAIImageProvider
    44	            provider = GenAIImageProvider(api_key='test-key')
    45	
    46	            # Create a fake image response
    47	            fake_image = Image.new('RGB', (100, 100), 'red')
    48	            mock_part = MagicMock()
    49	            mock_part.text = None
    50	            mock_part.as_image.return_value = fake_image
    51	            mock_response = MagicMock()
    52	            mock_response.parts = [mock_part]
    53	
    54	            provider.client.models.generate_content.return_value = mock_response
    55	
    56	            contents = [
    57	                {
    58	                    'role': 'user',
    59	                    'parts': [
    60	                        'restyle this',
    61	                        Image.new('RGB', (32, 24), 'blue'),
    62	                    ],
    63	                },
    64	                {'role': 'model', 'parts': ['ok']},
    65	            ]
    66	            result = provider.generate_image_from_conversation(
    67	                contents=contents,
    68	                aspect_ratio='16:9',
    69	                resolution='2K'
    70	            )
    71	
    72	            assert result is not None
    73	            assert isinstance(result, Image.Image)
    74	            provider.client.models.generate_content.assert_called_once()
    75	            serialized_contents = provider.client.models.generate_content.call_args.kwargs['contents']
    76	            assert isinstance(serialized_contents[0], genai_types.UserContent)
    77	            assert isinstance(serialized_contents[1], genai_types.ModelContent)
    78	            assert serialized_contents[0].parts[0].text == 'restyle this'
    79	            assert serialized_contents[0].parts[1].inline_data.mime_type == 'image/png'
    80	            assert serialized_contents[1].parts[0].text == 'ok'
```

## 11. 可观测性 Observability：Request Snapshot 记录在哪里

这条 restyle pipeline 的 debug instrumentation 做得其实挺好。

只要 debug mode 开启，或者发生 context degrade / fallback / error，系统就会往 `debug/restyle-context/<task_id>/...` 下面写 JSON artifacts。

也就是说你可以直接检查：

- prompt text
- 去掉 raw image bytes 之后的 serialized conversation contents
- selected 与 pruned images
- fallback decisions
- per-page saved versions

如果你要排 style drift 或 malformed request assembly，这基本是最快的入口，不用每次都 live 重跑一遍。

```bash
nl -ba backend/services/restyle_edit_debug.py | sed -n '19,145p'
```

```output
    19	def log_restyle_edit_event(event_name, trace, payload):
    20	    """Emit a searchable JSON log line for a restyle edit event."""
    21	    logger.info(
    22	        "restyle_edit_event %s",
    23	        json.dumps(
    24	            {
    25	                'event_name': event_name,
    26	                'trace': trace,
    27	                'event': payload,
    28	            },
    29	            ensure_ascii=False,
    30	            sort_keys=True,
    31	            default=str,
    32	        ),
    33	    )
    34	
    35	
    36	def build_task_artifact_path_components():
    37	    """Return the relative subdirectory used for task-scoped artifacts."""
    38	    return ['task']
    39	
    40	
    41	def build_page_artifact_path_components(*, page_number=None, page_id=None, version_number=None):
    42	    """Return the relative subdirectory used for page/version-scoped artifacts."""
    43	    page_label = page_id or 'unknown-page'
    44	    if page_number is None:
    45	        page_dir = f'page-unknown-{page_label}'
    46	    else:
    47	        page_dir = f'page-{int(page_number):03d}-{page_label}'
    48	
    49	    components = ['pages', page_dir]
    50	    if version_number is not None:
    51	        components.append(f'version-{int(version_number):03d}')
    52	    return components
    53	
    54	
    55	def serialize_conversation_contents(contents):
    56	    """Serialize provider-agnostic conversation contents without image bytes."""
    57	    serialized = []
    58	    for turn in contents:
    59	        parts = []
    60	        for part in turn.get('parts', []):
    61	            if 'text' in part:
    62	                parts.append({
    63	                    'type': 'text',
    64	                    'text': part['text'],
    65	                    'text_len': len(part['text']),
    66	                })
    67	            elif 'image_path' in part:
    68	                parts.append({
    69	                    'type': 'image',
    70	                    'image_path': part['image_path'],
    71	                })
    72	            else:
    73	                parts.append(part)
    74	        serialized.append({
    75	            'role': turn.get('role'),
    76	            'parts': parts,
    77	        })
    78	    return serialized
    79	
    80	
    81	def enrich_image_manifest(image_manifest):
    82	    """Attach stable file metadata to image manifest rows."""
    83	    enriched = []
    84	    for item in image_manifest:
    85	        path = item.get('path')
    86	        exists = bool(path) and Path(path).exists()
    87	        metadata = {
    88	            **item,
    89	            'exists': exists,
    90	        }
    91	        if exists:
    92	            metadata['sha256'] = _sha256_file(path)
    93	            metadata['file_size'] = Path(path).stat().st_size
    94	            width, height = _safe_image_size(path)
    95	            metadata['width'] = width
    96	            metadata['height'] = height
    97	        else:
    98	            metadata['sha256'] = None
    99	            metadata['file_size'] = None
   100	            metadata['width'] = None
   101	            metadata['height'] = None
   102	        enriched.append(metadata)
   103	    return enriched
   104	
   105	
   106	def maybe_write_debug_artifact(
   107	    config,
   108	    *,
   109	    event_name,
   110	    trace,
   111	    payload,
   112	    path_components=None,
   113	    degraded_context=False,
   114	    provider_fallback=False,
   115	    error=False,
   116	):
   117	    """Write an event artifact when debug mode or a notable condition is active."""
   118	    if not _should_capture(
   119	        config,
   120	        degraded_context=degraded_context,
   121	        provider_fallback=provider_fallback,
   122	        error=error,
   123	    ):
   124	        return None
   125	
   126	    task_id = trace.get('task_id') or 'unknown-task'
   127	    artifact_dir = Path(config.RESTYLE_EDIT_DEBUG_DIR) / task_id
   128	    for component in path_components or []:
   129	        artifact_dir = artifact_dir / component
   130	    artifact_dir.mkdir(parents=True, exist_ok=True)
   131	    artifact_path = artifact_dir / f'{event_name}.json'
   132	    artifact_path.write_text(
   133	        json.dumps(
   134	            {
   135	                'trace': trace,
   136	                'event_name': event_name,
   137	                'event': payload,
   138	            },
   139	            ensure_ascii=False,
   140	            indent=2,
   141	            sort_keys=True,
   142	            default=str,
   143	        )
   144	    )
   145	    return str(artifact_path)
```

## 12. 心智模型总结 Mental Model Summary

如果最后只记两种 request structure，记这两个就够了：

### 首轮 First Pass

- `contents = [prompt, original_slide, style_ref_1, style_ref_2, ...]`

### 编辑轮 Edit Pass

- `contents = [turn1_baseline_text, turn2_baseline_images, turn3_current_selected_image, turn4_delta_instruction_plus_extra_refs]`

整个 restyle subsystem，本质上就是围绕这组分裂设计出来的。

- first pass = 用 source slide + style refs 先生成一个 style-transferred baseline
- later pass = 再用 prompt snapshot + current image + delta instruction 去保持并微调这个 baseline

这也就是为什么会有 `restyle_base_prompt_snapshot` 这个字段，以及为什么 edit flow 明显比 first-pass flow 更复杂。
