const root = document.querySelector('#app');
const toastRoot = document.querySelector('#toast');
let stored = {};
try { stored = JSON.parse(sessionStorage.getItem('coursepilot.web.session') || '{}'); }
catch { sessionStorage.removeItem('coursepilot.web.session'); }
const state = {
  token: stored.token || '', userId: stored.userId || '', role: stored.role || '',
  page: stored.role === 'teacher' ? 'todo' : 'overview', authTab: 'login', courseId: '', materialId: '', examId: '',
  reviewAttemptId: '', sessionId: '', attemptId: '', paper: null, examResult: null,
  selectedQuestions: new Set(), chunkOffset: 0, sidebarCollapsed: Boolean(stored.sidebarCollapsed),
  composeOpen: false, questionSearch: '',
};
let renderVersion = 0;

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const enc = value => encodeURIComponent(String(value));
const money = value => Number(value ?? 0).toFixed(Number.isInteger(Number(value)) ? 0 : 1);
const empty = title => `<div class="empty"><strong>${esc(title)}</strong></div>`;
const tag = (value, kind = '') => `<span class="pill ${kind}">${esc(value)}</span>`;
const statusTag = status => {
  const labels = {indexed:'索引完成',already_indexed:'索引完成',indexing:'索引中',failed:'失败',
    ready_for_indexing:'解析完成',parse_failed:'解析失败',processing:'解析中',draft:'草稿',published:'已发布',
    active:'进行中',closed:'已结束',in_progress:'进行中',graded:'已判分',pending_review:'待批改',success:'成功',partial:'部分完成'};
  return tag(labels[status] || status || '未知', ['failed','parse_failed'].includes(status) ? 'error' :
    ['indexing','processing','pending_review','draft'].includes(status) ? 'warn' : '');
};
function saveLogin() {
  sessionStorage.setItem('coursepilot.web.session', JSON.stringify({token:state.token,userId:state.userId,role:state.role,sidebarCollapsed:state.sidebarCollapsed}));
}
function flash(message, error = false) {
  const item = document.createElement('div');
  item.className = `toast-item ${error ? 'error' : ''}`;
  item.textContent = message;
  toastRoot.append(item);
  setTimeout(() => item.remove(), 5500);
}
async function api(path, {method='GET', body, form} = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method,headers,body:form || (body === undefined ? undefined : JSON.stringify(body))});
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401 && state.token) {
      Object.assign(state,{token:'',userId:'',role:''}); saveLogin();
    }
    const detail = typeof payload === 'object' ? payload.detail : payload;
    const message=Array.isArray(detail)?detail.map(item=>{
      const path=item.loc||[];
      const row=typeof path[2]==='number'?`第 ${path[2]+2} 行 `:'';
      const field=path.filter(part=>typeof part==='string'&&!['body','items'].includes(part)).join('.');
      return `${row}${field?field+'：':''}${item.msg||'字段格式错误'}`;
    }).join('；'):detail;
    throw new Error(typeof message === 'string' ? message : `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}
function navItems() {
  if (state.role === 'teacher') return [
    ['todo','待办事项','✓'],['materials','课程资料','▤'],['questions','题库与考试','▦'],['review','主观题批改','✓']];
  if (state.role === 'student') return [
    ['overview','课程中心','◫'],['agent','AI 学习助手','✦'],['exams','课程考试','▦'],['results','考试成绩','▥']];
  return [['overview','教师审核','✓'],['courses','课程管理','▤'],['assignments','课程授权','▦']];
}
function shell() {
  return `<div class="shell ${state.sidebarCollapsed?'sidebar-collapsed':''}"><aside class="sidebar" id="main-sidebar">
    <div class="brand"><div class="brand-mark">C</div><div class="brand-text"><strong>CoursePilot</strong><small>课程学习平台</small></div></div>
    <div><nav class="nav" aria-label="主导航">${navItems().map(([key,name,icon])=>
      `<button type="button" data-action="navigate" data-page="${key}" title="${esc(name)}" aria-label="${esc(name)}" class="${state.page===key?'active':''}"><span class="icon">${icon}</span><span class="nav-label">${name}</span></button>`).join('')}</nav></div>
    <div class="side-bottom"><div class="account" title="${esc(state.userId)}"><div class="avatar">${esc(state.userId.slice(0,1).toUpperCase())}</div><div class="account-label"><strong>${esc(state.userId)}</strong><small>${esc({teacher:'教师',student:'学生',admin:'管理员'}[state.role]||state.role)}</small></div></div>
    <button type="button" class="ghost" data-action="logout" title="退出登录" aria-label="退出登录"><span class="logout-label">退出登录</span><span class="logout-icon" aria-hidden="true">↪</span></button></div>
  </aside><button type="button" class="sidebar-toggle" data-action="toggle-sidebar" aria-controls="main-sidebar" aria-expanded="${!state.sidebarCollapsed}" aria-label="${state.sidebarCollapsed?'展开':'收起'}侧边栏" title="${state.sidebarCollapsed?'展开':'收起'}侧边栏">${state.sidebarCollapsed?'☰':'‹'}</button><div class="workspace"><main class="content" id="content"></main></div></div>`;
}
function title(eyebrow, heading, subtitle, action = '') {
  return `<header class="page-title"><h1>${esc(heading)}</h1>${action}</header>`;
}
function authPage() {
  const tabs = [['login','账号登录'],['student','学生注册'],['teacher','教师注册']];
  const login = `<form data-form="login"><label class="field">用户 ID<input name="user_id" autocomplete="username" required placeholder="输入你的用户 ID"></label><label class="field">密码<input name="password" type="password" autocomplete="current-password" required placeholder="输入密码"></label><button class="btn primary" type="submit">登录工作台</button></form>`;
  const signup = `<form data-form="register"><label class="field">用户 ID<input name="user_id" required maxlength="50" placeholder="设置用户 ID"></label><label class="field">姓名<input name="name" required placeholder="你的姓名"></label><label class="field">密码<input name="password" type="password" required minlength="6" autocomplete="new-password" placeholder="设置密码"></label><button class="btn primary" type="submit">${state.authTab==='teacher'?'提交教师注册':'注册学生账号'}</button></form>`;
  return `<div class="auth-page"><header class="auth-header"><div class="brand"><div class="brand-mark">C</div><strong>CoursePilot <span>课程学习平台</span></strong></div></header>
    <main class="auth-form-area"><div class="auth-panel"><h1>欢迎登录</h1>
    <div class="tabs" role="tablist">${tabs.map(([key,label])=>`<button type="button" role="tab" aria-selected="${state.authTab===key}" class="${state.authTab===key?'active':''}" data-action="auth-tab" data-tab="${key}">${label}</button>`).join('')}</div>
    ${state.authTab==='login'?login:signup}${state.authTab==='teacher'?'<div class="notice">教师注册后需等待管理员审核。</div>':''}</div></main></div>`;
}
async function render() {
  const version = ++renderVersion;
  if (!state.token) { root.innerHTML = authPage(); return; }
  root.innerHTML = shell();
  const main = document.querySelector('#content');
  main.innerHTML = `<div class="empty">正在加载工作区…</div>`;
  try {
    const html = await pageHtml();
    if (version === renderVersion) {
      main.innerHTML = html;
      if (state.page === 'agent') requestAnimationFrame(()=>{
        const messages=main.querySelector('.messages');
        if(messages) messages.scrollTop=messages.scrollHeight;
      });
    }
  } catch (error) {
    if (!state.token) return render();
    if (version === renderVersion) main.innerHTML = `<div class="notice error">${esc(error.message)}</div><button type="button" class="btn" data-action="refresh">重试</button>`;
  }
}
async function pageHtml() {
  if (state.role === 'admin') return adminPage();
  if (state.role === 'teacher') return ({todo:teacherTodo,materials:teacherMaterials,questions:teacherQuestions,review:teacherReview}[state.page]||teacherTodo)();
  return ({overview:studentOverview,agent:studentAgent,exams:studentExams,results:studentResults}[state.page]||studentOverview)();
}
async function adminPage() {
  if (state.page==='courses') {
    const courses=await api('/api/courses/admin');
    return title('ADMIN / COURSES','课程管理','')+
      `<h2 class="section-title">创建课程</h2><div class="card"><form data-form="create-course"><div class="grid"><label class="field">课程代码<input name="code" maxlength="50" required placeholder="例如 PYTHON101"></label><label class="field">课程名称<input name="name" maxlength="100" required placeholder="输入课程名称"></label></div><label class="field">课程简介<textarea name="description" rows="2"></textarea></label><div class="action-row"><button class="btn primary" type="submit">创建草稿</button></div></form></div>
      <h2 class="section-title">课程发布</h2>${courses.length?`<div class="table-wrap"><table><thead><tr><th>课程</th><th>状态</th><th>操作</th></tr></thead><tbody>${courses.map(c=>`<tr><td>${esc(c.name)} · ${esc(c.code)}</td><td>${tag(c.status==='draft'?'草稿':c.status==='active'?'已发布':c.status)}</td><td>${c.status==='draft'?`<button class="btn small primary" data-action="publish-course" data-id="${esc(c.course_id)}">确认发布</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('尚未创建课程')}`;
  }
  if (state.page==='assignments') {
    const [options,assignments]=await Promise.all([
      api('/api/teachers/assignment-options'),api('/api/teachers/assignments'),
    ]);
    return title('ADMIN / ASSIGNMENTS','课程授权','')+
      `<h2 class="section-title">分配教师课程</h2><div class="card">${options.teachers.length&&options.courses.length?`<form data-form="assign-course"><div class="grid"><label class="field">教师<select name="teacher_id" required>${options.teachers.map(t=>`<option value="${esc(t.user_id)}">${esc(t.name)} · ${esc(t.user_id)}</option>`).join('')}</select></label><label class="field">课程<select name="course_id" required>${options.courses.map(c=>`<option value="${esc(c.course_id)}">${esc(c.name)} · ${esc(c.code)}</option>`).join('')}</select></label></div><div class="action-row"><button class="btn primary" type="submit">确认分配</button></div></form>`:empty(options.teachers.length?'请先发布课程':'暂无已审核教师')}</div>
      <h2 class="section-title">现有授权</h2>${assignments.length?`<div class="table-wrap"><table><thead><tr><th>教师</th><th>课程</th><th>操作</th></tr></thead><tbody>${assignments.map(a=>`<tr><td>${esc(a.teacher_name)} · ${esc(a.teacher_id)}</td><td>${esc(a.course_name)} · ${esc(a.course_code)}</td><td><button class="btn small danger" data-action="revoke-assignment" data-teacher="${esc(a.teacher_id)}" data-course="${esc(a.course_id)}">撤销授权</button></td></tr>`).join('')}</tbody></table></div>`:empty('暂无教师课程授权')}`;
  }
  const pending=await api('/api/teachers/pending');
  return title('ADMIN / TEACHERS','教师审核','')+
    `<div class="grid"><div class="card"><div class="stat-label">待审核教师</div><div class="stat-value">${pending.length}</div></div></div>
    <h2 class="section-title">教师注册审核</h2>${pending.length?`<div class="stack">${pending.map(t=>`<div class="card row"><div><strong>${esc(t.name)}</strong><div class="small muted mono">${esc(t.user_id)}</div></div><button type="button" class="btn primary" data-action="approve" data-id="${esc(t.user_id)}">批准账号</button></div>`).join('')}</div>`:empty('暂无待审核账号')}`;
}
async function teacherCourses() { return api('/api/teachers/me/courses'); }
async function teacherTodo() {
  const courses=await teacherCourses();
  const groups=await Promise.all(courses.map(async course=>{
    const [materials,pending]=await Promise.all([
      api(`/api/teacher/course-materials/courses/${enc(course.course_id)}/index-status`),
      api(`/api/exams/review/pending?course_id=${enc(course.course_id)}`),
    ]);
    const tasks=[];
    for(const material of materials) {
      if(material.source_type!=='teacher'||material.uploaded_by!==state.userId) continue;
      if(material.parse_status==='parse_failed'||Object.values(material.indexes||{}).some(index=>index.status==='failed'))
        tasks.push({type:'material',id:material.material_id,label:`${material.title} · 解析或索引失败`});
      else if(material.parse_status==='ready_for_indexing') {
        let offset=0, needsReview=false;
        do {
          const detail=await api(`/api/teacher/course-materials/${enc(material.material_id)}/chunk-topics?offset=${offset}&limit=50`);
          needsReview=detail.chunks.some(chunk=>!chunk.reviewed);
          offset+=detail.chunks.length;
          if(needsReview||offset>=detail.total||!detail.chunks.length) break;
        } while(true);
        if(needsReview) tasks.push({type:'material',id:material.material_id,label:`${material.title} · 待审核片段标签`});
      }
    }
    for(const attempt of pending) tasks.push({type:'review',id:attempt.attempt_id,label:`学生 ${attempt.student_id} · 主观题待批改`});
    return {course,tasks};
  }));
  const total=groups.reduce((count,group)=>count+group.tasks.length,0);
  return title('TEACHER / TODO','待办事项','')+
    `<div class="section-summary">${total} 项待处理</div>${groups.map(({course,tasks})=>
      `<section class="content-section"><h2 class="section-title">${esc(course.name)}</h2>${tasks.length?
        `<div class="stack">${tasks.map(task=>`<div class="card row"><strong>${esc(task.label)}</strong><button class="btn" data-action="open-teacher-todo" data-type="${task.type}" data-course="${esc(course.course_id)}" data-id="${esc(task.id)}">处理</button></div>`).join('')}</div>`:
        empty('当前课程暂无待办')}</section>`).join('')}`;
}
function courseSelect(courses) {
  if (!state.courseId || !courses.some(c=>c.course_id===state.courseId)) state.courseId=courses[0]?.course_id||'';
  return `<label class="field">当前课程<select data-select="course">${courses.map(c=>`<option value="${esc(c.course_id)}" ${c.course_id===state.courseId?'selected':''}>${esc(c.code)} · ${esc(c.name)}</option>`).join('')}</select></label>`;
}
async function teacherMaterials() {
  const courses=await teacherCourses();
  if (!courses.length) return title('TEACHER / MATERIALS','课程资料','管理课程资料与审核片段标签。')+empty('尚未分配课程');
  const picker=courseSelect(courses);
  const materials=await api(`/api/teacher/course-materials/courses/${enc(state.courseId)}/index-status`);
  if (!materials.some(m=>m.material_id===state.materialId&&m.parse_status==='ready_for_indexing'))
    state.materialId=materials.find(m=>m.source_type==='teacher'&&m.uploaded_by===state.userId&&m.parse_status==='ready_for_indexing')?.material_id||'';
  const ready=materials.filter(m=>Object.values(m.indexes||{}).some(v=>v.status==='indexed')).length;
  let review='';
  if (state.materialId) {
    const detail=await api(`/api/teacher/course-materials/${enc(state.materialId)}/chunk-topics?offset=${state.chunkOffset}&limit=50`);
    const reviewed=detail.chunks.filter(c=>c.reviewed).length;
    review=`<div class="row"><h2 class="section-title">片段标签审核</h2>${tag(`本页已核对 ${reviewed}/${detail.chunks.length}`)}</div>
      <div class="notice warn">建议标签未经教师确认，不会直接作为复习计划的可信资料。标签应尽量与该课程题目的知识点名称一致。</div>
      <div class="stack">${detail.chunks.map(c=>`<div class="card"><div class="row"><div><div class="eyebrow">CHUNK ${c.chunk_index+1} / ${detail.total}</div><h3>${esc(c.section||'未标注章节')}</h3></div>${statusTag(c.reviewed?'success':'pending_review')}</div>
        <div class="material-text">${esc(c.content)}</div><div class="action-row tag-list">${c.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
        <form data-form="chunk-topics" data-index="${c.chunk_index}" class="action-row"><label class="field" style="flex:1;min-width:240px">确认的知识点<input name="topics" value="${esc(c.topics.join(', '))}" required maxlength="405" aria-label="第 ${c.chunk_index+1} 段知识点"><span class="field-hint">1～4 个，用逗号分隔；可改写或新增</span></label><button class="btn primary" type="submit">保存并重建索引</button></form></div>`).join('')}</div>
      ${detail.total>50?`<div class="action-row"><button class="btn" data-action="chunks-prev" ${state.chunkOffset===0?'disabled':''}>上一页</button><button class="btn" data-action="chunks-next" ${state.chunkOffset+50>=detail.total?'disabled':''}>下一页</button></div>`:''}`;
  }
  return title('TEACHER / MATERIALS','课程资料','',`<button class="btn" data-action="refresh">刷新状态</button>`)+
    `<div class="filter-row">${picker}</div>
    <section class="content-section"><div class="section-heading"><h2>资料列表</h2><div class="section-summary">${materials.length} 份资料 · ${ready} 份索引可用</div></div>
    ${materials.length?`<div class="table-wrap"><table><thead><tr><th>资料</th><th>文件</th><th>解析</th><th>主索引</th><th>备索引</th><th>操作</th></tr></thead><tbody>${materials.map(m=>`<tr><td><strong>${esc(m.title)}</strong></td><td>${esc(m.filename)}</td><td>${statusTag(m.parse_status)}${m.parse_error?`<div class="small muted">${esc(m.parse_error)}</div>`:''}</td><td>${m.indexes?.primary?statusTag(m.indexes.primary.status):tag('等待索引','neutral')}</td><td>${m.indexes?.backup?statusTag(m.indexes.backup.status):tag('等待索引','neutral')}</td><td>${m.source_type==='teacher'&&m.uploaded_by===state.userId&&m.parse_status==='ready_for_indexing'?`<button class="btn small ${m.material_id===state.materialId?'primary':''}" data-action="select-material" data-id="${esc(m.material_id)}">审核标签</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('这门课程还没有资料')}</section>
    ${review?`<section class="content-section">${review}</section>`:''}
    <section class="content-section"><h2 class="section-title">上传资料</h2><div class="card"><form data-form="upload-material" enctype="multipart/form-data"><div class="grid upload-fields"><label class="field">资料标题<input name="title" required placeholder="输入资料标题"></label><label class="field">资料文件<input name="file" type="file" accept=".md,.txt,.pdf,.docx,.pptx" required><span class="field-hint">支持 MD、TXT、PDF、DOCX、PPTX，最大 20 MB</span></label></div><div class="action-row"><button class="btn primary" type="submit">上传资料</button></div></form></div></section>`;
}

const csvTemplate=[
  ['question_type','topic','stem','options','answer_key','explanation','max_score','knowledge_count_level','reasoning_level','transfer_level','distractor_level'],
  ['single_choice','Python列表','列表首个元素的下标是什么？',JSON.stringify({A:'0',B:'1'}),JSON.stringify('A'),'下标从零开始',1,0,0,0,0],
  ['multiple_choice','Python类型','哪些是可变序列？',JSON.stringify({A:'列表',B:'字典',C:'元组'}),JSON.stringify(['A']),'列表是可变序列',2,1,0,0,1],
  ['true_false','Python语法','Python 列表可以修改吗？','',JSON.stringify(true),'列表是可变对象',1,0,0,0,0],
  ['fill_blank','Python列表','列表第一个下标是几？','',JSON.stringify(['0','零']),'下标从零开始',1,0,0,0,0],
  ['short_answer','Python函数','解释 return 的作用。','',JSON.stringify('结束函数并返回结果'),'由教师按参考答案批改',5,1,1,0,0],
].map(row=>row.map(value=>{
  const cell=String(value);
  return /[",\r\n]/.test(cell)?`"${cell.replaceAll('"','""')}"`:cell;
}).join(',')).join('\n')+'\n';
async function teacherQuestions() {
  const courses=await teacherCourses();
  if (!courses.length) return title('TEACHER / ASSESS','题库与考试','从真实题库组织测评。')+empty('尚未分配课程');
  const picker=courseSelect(courses);
  const [questions,exams]=await Promise.all([
    api(`/api/teacher/courses/${enc(state.courseId)}/questions`),
    api(`/api/exams/teacher?course_id=${enc(state.courseId)}`),
  ]);
  const details=await Promise.all(exams.map(exam=>api(`/api/exams/teacher/${enc(exam.exam_id)}`)));
  const examDetails=new Map(details.map(detail=>[detail.exam_id,detail]));
  if (!exams.some(exam=>exam.exam_id===state.examId)) state.examId='';
  const typeLabel={single_choice:'单选',multiple_choice:'多选',true_false:'判断',fill_blank:'填空',short_answer:'简答'};
  const search=state.questionSearch.trim().toLocaleLowerCase();
  return title('TEACHER / ASSESS','题库与考试','')+
    `<div class="assessment-overview"><div class="assessment-course">${picker}</div><div class="assessment-counts"><span><strong>${questions.length}</strong> 道题目</span><span><strong>${exams.length}</strong> 份试卷</span><span><strong>${exams.filter(exam=>exam.status==='published').length}</strong> 份已发布</span></div></div>
    <section class="assessment-import" aria-labelledby="import-heading"><div class="assessment-section-head"><h2 id="import-heading">导入题目</h2><button class="btn small" data-action="download-csv">下载 CSV 模板</button></div><form data-form="import-questions"><div class="assessment-import-row"><label class="csv-upload-button"><input type="file" name="file" accept=".csv,text/csv" aria-label="选择 CSV 文件" required><span aria-hidden="true">选择 CSV 文件</span></label><span class="assessment-file-status" data-import-status role="status">未选择文件，请先选择 CSV 文件</span><button class="btn primary" type="submit" disabled title="请先选择 CSV 文件">确认导入</button></div><div data-import-preview aria-live="polite"></div></form></section>
    <div class="assessment-columns"><section class="assessment-panel" aria-labelledby="bank-heading"><div class="assessment-section-head"><h2 id="bank-heading">题库管理</h2><span class="section-summary">${questions.length} 道题目</span></div>${questions.length?`<label class="assessment-search">搜索题干或知识点<input type="search" data-question-search value="${esc(state.questionSearch)}" placeholder="输入题干或知识点"></label><div class="assessment-list-head" data-search-count>${search?`找到 ${questions.filter(q=>`${q.stem} ${q.topic}`.toLocaleLowerCase().includes(search)).length} 道题目`:'全部题目'}</div><div class="assessment-question-list">${questions.map(q=>`<article class="assessment-question" data-question-row data-search="${esc(`${q.stem} ${q.topic}`.toLocaleLowerCase())}" ${search&&!`${q.stem} ${q.topic}`.toLocaleLowerCase().includes(search)?'hidden':''}><strong>${esc(q.stem)}</strong><div class="assessment-meta"><span>${esc(q.topic)}</span>${tag(typeLabel[q.question_type]||q.question_type,'neutral')}</div></article>`).join('')}</div>`:`<div class="assessment-empty"><strong>题库还没有题目</strong><span>请先使用上方入口导入 CSV 文件。</span></div>`}</section>
    <section class="assessment-panel" aria-labelledby="exam-heading"><div class="assessment-section-head"><h2 id="exam-heading">试卷管理</h2><button class="btn primary small" data-action="toggle-compose" ${questions.length?'':'disabled title="题库为空，请先导入题目"'}>创建试卷</button></div>${!questions.length?'<p class="assessment-inline-hint">题库为空，请先导入题目后组卷。</p>':''}
    ${state.composeOpen&&questions.length?`<form class="assessment-composer" data-form="create-exam"><div class="assessment-composer-head"><strong>创建试卷草稿</strong><button type="button" class="btn small" data-action="close-compose">取消</button></div><div class="grid"><label class="field">试卷名称<input name="title" required placeholder="输入试卷名称"></label><label class="field">时长（分钟）<input name="duration" type="number" min="1" value="30" required></label></div><div class="assessment-list-head">从题库选择题目并设置分值</div><div class="assessment-composer-questions">${questions.map(q=>`<label class="assessment-pick-question"><input aria-label="选择题目 ${esc(q.question_id)}" type="checkbox" data-question="${esc(q.question_id)}" ${state.selectedQuestions.has(q.question_id)?'checked':''}><span><strong>${esc(q.stem)}</strong><small>${esc(q.topic)} · ${esc(typeLabel[q.question_type]||q.question_type)}</small></span><input aria-label="${esc(q.question_id)} 分值" data-points="${esc(q.question_id)}" type="number" min="0.5" step="0.5" value="${esc(q.max_score)}"></label>`).join('')}</div><button class="btn primary" type="submit">创建草稿</button></form>`:''}
    ${exams.length?`<div class="assessment-exam-list">${exams.map(exam=>{const detail=examDetails.get(exam.exam_id);return `<article class="assessment-exam"><div class="assessment-exam-title"><strong>${esc(exam.title)}</strong>${statusTag(exam.status)}</div><div class="assessment-meta">${detail.questions.length} 道题 · ${esc(detail.duration_minutes)} 分钟 · ${money(detail.total_points)} 分</div><div class="assessment-actions"><button type="button" class="btn small" data-action="select-exam" data-id="${esc(exam.exam_id)}">${state.examId===exam.exam_id?'收起预览':'预览'}</button>${exam.status==='draft'?`<button type="button" class="btn small primary" data-action="publish-exam" data-id="${esc(exam.exam_id)}">发布</button>`:''}</div>${state.examId===exam.exam_id?`<div class="assessment-preview">${detail.questions.map(q=>`<div class="assessment-preview-question"><strong>${q.position}. ${esc(q.stem)}</strong><span>${esc(q.topic)} · ${money(q.points)} 分</span></div>`).join('')}</div>`:''}</article>`}).join('')}</div>`:`<div class="assessment-empty"><strong>还没有试卷</strong><span>${questions.length?'点击“创建试卷”，从题库选择题目。':'先导入题目，再创建试卷。'}</span></div>`}</section></div>`;
}

async function teacherReview() {
  const courses=await teacherCourses();
  if (!courses.length) return title('TEACHER / REVIEW','主观题批改','依据参考答案审核学生作答。')+empty('尚未分配课程');
  const picker=courseSelect(courses);
  const pending=await api(`/api/exams/review/pending?course_id=${enc(state.courseId)}`);
  if (!pending.some(item=>String(item.attempt_id)===String(state.reviewAttemptId))) state.reviewAttemptId=String(pending[0]?.attempt_id||'');
  const detail=state.reviewAttemptId?await api(`/api/exams/review/${enc(state.reviewAttemptId)}`):null;
  return title('TEACHER / REVIEW','主观题批改','查看学生答案与参考答案，逐题给分后生成最终成绩。')+
    `<div class="filter-row">${picker}</div><div class="grid"><div class="card"><div class="stat-label">待批改记录</div><div class="stat-value">${pending.length}</div></div><div class="card"><div class="stat-label">当前课程</div><div class="stat-value" style="font-size:1.2rem">${esc(courses.find(c=>c.course_id===state.courseId)?.name)}</div></div></div>
    <h2 class="section-title">批改队列</h2>${pending.length?`<div class="grid"><div class="stack">${pending.map(item=>`<button class="session-item ${String(item.attempt_id)===state.reviewAttemptId?'active':''}" data-action="select-review" data-id="${item.attempt_id}"><strong>记录 ${item.attempt_id}</strong><br><span class="small muted">学生 ${esc(item.student_id)}</span></button>`).join('')}</div>${detail?`<div class="card"><h2>${esc(detail.exam_title)}</h2><p>学生 ${esc(detail.student_id)}</p><form data-form="grade-review" data-id="${detail.attempt_id}">${detail.questions.map(q=>`<div class="card"><strong>第 ${q.position} 题 · ${esc(q.stem)}</strong><p>学生作答：${esc(q.answer)}</p><p>参考答案：${esc(q.reference_answer)}</p><p>解析：${esc(q.explanation||'无')}</p><label class="field">得分（满分 ${money(q.points)}）<input type="number" name="score-${esc(q.question_id)}" min="0" max="${esc(q.points)}" step="0.5" value="0" required></label></div>`).join('')}<div><button class="btn primary" type="submit">提交批改结果</button></div></form></div>`:''}</div>`:empty('暂无待批改记录','包含简答题的试卷提交后会出现在这里。')}`;
}

async function studentOverview() {
  const [available,mine]=await Promise.all([api('/api/courses'),api('/api/courses/mine')]);
  const enrolled=new Set(mine.map(c=>c.course_id));
  const notEnrolled=available.filter(c=>!enrolled.has(c.course_id));
  return title('STUDENT / COURSES','课程中心','')+
    `<section class="content-section"><div class="section-heading"><h2>我的课程</h2><span class="section-summary">${mine.length} 门</span></div>${mine.length?`<div class="grid">${mine.map(c=>`<div class="card course-card"><div class="row"><h2>${esc(c.name)}</h2>${tag(c.code)}</div>${c.description?`<p>${esc(c.description)}</p>`:''}<div class="action-row"><button class="btn primary" data-action="open-agent" data-id="${esc(c.course_id)}">进入学习助手</button></div></div>`).join('')}</div>`:empty('还没有选择课程')}</section>
    <section class="content-section"><div class="section-heading"><h2>可选课程</h2><span class="section-summary">${notEnrolled.length} 门</span></div>${notEnrolled.length?`<div class="grid">${notEnrolled.map(c=>`<div class="card course-card"><div class="row"><h2>${esc(c.name)}</h2>${tag(c.code,'neutral')}</div>${c.description?`<p>${esc(c.description)}</p>`:''}<div class="action-row"><button class="btn" data-action="enroll" data-id="${esc(c.course_id)}">加入课程</button></div></div>`).join('')}</div>`:empty('暂无其他可选课程')}</section>`;
}
function planHtml(plan, messageId, progress) {
  if (!plan) return '';
  const tasks=plan.review_tasks||[];
  return `<div class="card" style="margin-top:12px"><div class="row"><strong>结构化复习计划</strong>${statusTag(plan.status)}</div>
    ${(plan.limitations||[]).map(text=>`<div class="notice warn">${esc(text)}</div>`).join('')}
    ${(plan.wrong_question_evidence||[]).length?`<h4>错题证据</h4><div class="action-row">${plan.wrong_question_evidence.map(q=>`<button class="btn small" data-action="view-plan-wrong" data-message="${esc(messageId)}" data-id="${esc(q.question_id)}">查看 ${esc(q.question_id)}</button>`).join('')}</div>`:''}
    ${(plan.material_evidence||[]).length?`<h4>课程资料</h4><div class="action-row">${plan.material_evidence.map(m=>`<button class="btn small" data-action="view-plan-material" data-message="${esc(messageId)}" data-id="${esc(m.chunk_id)}">${esc(m.source_title)} · ${esc(m.section||m.chunk_id)}</button>`).join('')}</div>`:''}
    ${tasks.length?tasks.map(task=>{
      const done=progress.get(`${messageId}:${task.task_id}`);
      return `<div class="plan-task"><h4>${esc(task.priority_rank)} · ${esc(task.topic)} ${done?tag('已完成'):''}</h4><p>${esc(task.objective)}</p><ol>${(task.action_steps||[]).map(step=>`<li>${esc(step)}</li>`).join('')}</ol><form data-form="complete-review-task" data-message="${esc(messageId)}" data-task="${esc(task.task_id)}"><strong>完成后自测</strong>${(task.self_check_questions||[]).map((q,index)=>`<label class="field">${esc(q)}<textarea name="answer-${index}" rows="2" required>${esc(done?.answers?.[index]||'')}</textarea></label>`).join('')}<button class="btn small primary" type="submit">${done?'更新自测记录':'提交自测并完成'}</button></form></div>`;
    }).join(''):'<p class="small muted">当前没有可生成的可信复习任务。</p>'}</div>`;
}
async function studentAgent() {
  const [allSessions,courses]=await Promise.all([api('/api/sessions'),api('/api/courses/mine')]);
  const sessions=allSessions.filter(s=>s.status==='active'&&s.course_id);
  if (!sessions.some(s=>s.session_id===state.sessionId)) state.sessionId=sessions[0]?.session_id||'';
  const current=sessions.find(s=>s.session_id===state.sessionId);
  const [history, progressRows]=current?await Promise.all([
    api(`/api/sessions/${enc(state.sessionId)}/messages?limit=100`),
    api(`/api/sessions/${enc(state.sessionId)}/review-task-progress`),
  ]):[{messages:[]},[]];
  const progress=new Map(progressRows.map(row=>[`${row.message_id}:${row.task_id}`,row]));
  return title('STUDENT / AI ASSISTANT','AI 学习助手','')+
    `<div class="chat-layout"><aside class="card"><h3>学习会话</h3><label class="field">新会话课程<select data-select="agent-course">${courses.map(c=>`<option value="${esc(c.course_id)}" ${c.course_id===state.courseId?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><div class="action-row"><button class="btn small" data-action="new-session" ${courses.length?'':'disabled'}>＋ 新建会话</button></div><div class="divider"></div>
    <div class="session-list">${sessions.length?sessions.map(s=>`<button class="session-item ${s.session_id===state.sessionId?'active':''}" data-action="select-session" data-id="${esc(s.session_id)}"><strong>${esc(s.title||'学习对话')}</strong><br><span class="small muted">${esc(s.course_id)}</span></button>`).join(''):empty('暂无会话','请先选课，再创建学习会话。')}</div></aside>
    <section class="card chat-panel"><div class="row"><div><h2>${esc(current?.title||'开始新的学习对话')}</h2><div class="small muted">${esc(current?.course_id||'选择课程后开始')}</div></div>${current?`<button class="btn small danger" data-action="close-session">结束会话</button>`:''}</div>
    <div class="messages">${history.messages.length?history.messages.filter(m=>['user','assistant'].includes(m.role)).map(m=>`<div class="message ${m.role==='user'?'user':'assistant'}">${esc(m.content)}${m.role==='assistant'?planHtml(m.review_plan,m.message_id,progress):''}${m.called_tools?.length?`<div class="message-meta">调用工具：${esc(m.called_tools.join(' → '))}</div>`:''}</div>`).join(''):empty('从一个问题开始','试着提问：“根据我的错题制定复习计划”。')}</div>
    <div id="plan-evidence" aria-live="polite"></div>
    ${current?`<form data-form="chat" class="chat-input"><input name="message" required autocomplete="off" placeholder="询问错题、知识点或复习计划"><button class="btn primary" type="submit">发送</button></form>`:'<p class="small muted">从课程中心进入，或使用左侧“新建”开始。</p>'}</section></div>`;
}
function examQuestion(q) {
  const name=`answer-${q.question_id}`,options=q.options||{};
  const entries=Array.isArray(options)?options.map(v=>[v,String(v)]):Object.entries(options);
  let control='';
  if (q.question_type==='single_choice'||q.question_type==='multiple_choice')
    control=entries.map(([key,value])=>`<label class="check-row"><input type="${q.question_type==='single_choice'?'radio':'checkbox'}" name="${esc(name)}" value="${esc(key)}"><span><strong>${esc(key)}</strong> · ${esc(value)}</span></label>`).join('');
  else if (q.question_type==='true_false') control=`<label class="check-row"><input type="radio" name="${esc(name)}" value="true">正确</label><label class="check-row"><input type="radio" name="${esc(name)}" value="false">错误</label>`;
  else if (q.question_type==='fill_blank') control=`<label class="field">你的答案<input name="${esc(name)}" autocomplete="off"></label>`;
  else control=`<label class="field">你的回答<textarea name="${esc(name)}" rows="5"></textarea></label>`;
  return `<div class="card" data-question-id="${esc(q.question_id)}" data-type="${esc(q.question_type)}"><div class="eyebrow">QUESTION ${q.position}</div><h3>${esc(q.stem)}</h3><p class="small muted">${money(q.points)} 分</p>${control}</div>`;
}
function resultHtml(result) {
  if (!result) return '';
  if (result.status==='pending_review') return `<div class="notice warn">${esc(result.message||'简答题待教师批改，最终成绩尚未生成。')}</div><button class="btn" data-action="refresh-result">刷新批改状态</button>`;
  const answerText=(value,options)=>{
    if(value===null||value===undefined||(typeof value==='object'&&!Array.isArray(value))) return '未作答';
    if(Array.isArray(value)) return value.map(item=>answerText(item,options)).join('、');
    if(typeof value==='boolean') return value?'正确':'错误';
    const key=String(value);
    return options&&Object.prototype.hasOwnProperty.call(options,key)?`${key} · ${options[key]}`:key;
  };
  return `<div class="grid"><div class="card"><div class="stat-label">本次得分</div><div class="stat-value">${money(result.total_score)} / ${money(result.full_score)}</div></div><div class="card"><div class="stat-label">考试记录</div><div class="stat-value mono" style="font-size:1.25rem">${esc(result.attempt_id)}</div></div></div>
    <h2 class="section-title">逐题反馈</h2><div class="table-wrap"><table><thead><tr><th>题目</th><th>我的答案</th><th>参考答案</th><th>得分</th></tr></thead><tbody>${(result.answers||[]).map(a=>`<tr><td><strong>${esc(a.stem||a.question_id)}</strong><div class="small muted">${esc(a.topic||'')}</div></td><td>${esc(answerText(a.answer,a.options))}</td><td>${esc(answerText(a.correct_answer,a.options))}${a.explanation?`<div class="small muted">${esc(a.explanation)}</div>`:''}</td><td>${esc(a.score??'—')} / ${esc(a.points??'—')}</td></tr>`).join('')}</tbody></table></div>`;
}
async function studentExams() {
  if (state.examResult) return title('STUDENT / EXAM','考试结果','本次作答已提交。',`<button class="btn" data-action="back-exams">返回考试列表</button>`)+resultHtml(state.examResult);
  if (state.paper) return title('STUDENT / EXAM',state.paper.exam_title,'请完成每道题后提交；提交后将无法再次修改。')+
    `<div class="notice warn">提交截止时间：${esc(state.paper.deadline)}</div><form data-form="submit-exam" data-attempt="${esc(state.attemptId)}"><div class="stack">${state.paper.questions.map(examQuestion).join('')}</div><div class="action-row"><button class="btn primary" type="submit">提交试卷</button></div></form>`;
  const [exams,attempts]=await Promise.all([api('/api/exams/available'),api('/api/exams/attempts/mine')]);
  const byExam=new Map(attempts.map(item=>[item.exam_id,item]));
  return title('STUDENT / EXAM','课程考试','参加已发布的考试，完成后查看客观题成绩与教师批改结果。')+
    `<div class="grid">${exams.length?exams.map(e=>{
      const attempt=byExam.get(e.exam_id);
      const expired=attempt?.status==='in_progress'&&Date.now()>Date.parse(attempt.deadline+'Z');
      const action=!attempt?`<button class="btn primary" data-action="start-exam" data-id="${esc(e.exam_id)}">开始考试</button>`:
        attempt.status==='in_progress'?`<button class="btn primary" data-action="${expired?'finish-expired-exam':'resume-exam'}" data-id="${esc(attempt.attempt_id)}">${expired?'结算超时试卷':'继续考试'}</button>`:
        `<button class="btn" data-action="open-result" data-id="${esc(attempt.attempt_id)}">${attempt.status==='pending_review'?'查看批改状态':'查看成绩'}</button>`;
      return `<div class="card raised"><h2>${esc(e.title)}</h2><p>${esc(e.course_name)} · ${esc(e.duration_minutes)} 分钟</p><div class="action-row">${attempt?statusTag(attempt.status):tag('未参加','neutral')}${action}</div></div>`;
    }).join(''):empty('当前没有可参加的考试')}</div>`;
}
async function studentResults() {
  const attempts=await api('/api/exams/attempts/mine');
  return title('STUDENT / RESULTS','考试成绩','')+
    `${attempts.length?`<div class="table-wrap"><table><thead><tr><th>考试</th><th>课程</th><th>状态</th><th>成绩</th><th>操作</th></tr></thead><tbody>${attempts.map(item=>`<tr><td>${esc(item.exam_title)}</td><td>${esc(item.course_name)}</td><td>${statusTag(item.status)}</td><td>${item.total_score==null?'—':money(item.total_score)}</td><td>${item.status==='in_progress'?`<button class="btn small" data-action="${Date.now()>Date.parse(item.deadline+'Z')?'finish-expired-exam':'resume-exam'}" data-id="${esc(item.attempt_id)}">${Date.now()>Date.parse(item.deadline+'Z')?'结算超时试卷':'继续考试'}</button>`:`<button class="btn small" data-action="open-result" data-id="${esc(item.attempt_id)}">查看详情</button>`}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无考试记录')}
    ${state.examResult?`<h2 class="section-title">考试详情</h2>${resultHtml(state.examResult)}`:''}`;
}

function parseCsv(text, courseId) {
  const rows=[]; let row=[], cell='', quoted=false;
  text=text.replace(/^\uFEFF/,'');
  for (let i=0;i<text.length;i++) {
    const char=text[i];
    if (char==='"') { if (quoted&&text[i+1]==='"') {cell+='"';i++;} else quoted=!quoted; }
    else if (char===','&&!quoted) {row.push(cell);cell='';}
    else if ((char==='\n'||char==='\r')&&!quoted) {if(char==='\r'&&text[i+1]==='\n') i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell='';}
    else cell+=char;
  }
  if (quoted) throw new Error('CSV 引号未闭合');
  row.push(cell);if(row.some(x=>x.trim()))rows.push(row);
  const header=rows.shift()||[];
  for (const field of ['question_type','topic','stem','answer_key']) if(!header.includes(field)) throw new Error(`CSV 缺少必填列：${field}`);
  const items=rows.map((values,index)=>{
    if(values.length!==header.length) throw new Error(`第 ${index+2} 行列数不符合表头；含逗号内容请用双引号包裹`);
    const input=Object.fromEntries(header.map((key,i)=>[key,values[i]?.trim()||'']));
    const parseJson=field=>{try{return JSON.parse(input[field]);}catch{throw new Error(`第 ${index+2} 行 ${field}：JSON 格式错误`);}};
    {
      const line=index+2;
      if(!['single_choice','multiple_choice','true_false','fill_blank','short_answer'].includes(input.question_type)) throw new Error(`第 ${line} 行 question_type：不支持的题型`);
      if(!input.topic) throw new Error(`第 ${line} 行 topic：知识点不能为空`);
      if(!input.stem) throw new Error(`第 ${line} 行 stem：题干不能为空`);
      const score=Number(input.max_score||1);
      if(!Number.isFinite(score)||score<=0) throw new Error(`第 ${index+2} 行 max_score：必须大于 0`);
      const levels=Object.fromEntries(['knowledge_count_level','reasoning_level','transfer_level','distractor_level'].map(key=>{
        const value=Number(input[key]||0);
        if(!Number.isInteger(value)||value<0||value>2) throw new Error(`第 ${index+2} 行 ${key}：必须是 0～2`);
        return [key,value];
      }));
      const options=input.options?parseJson('options'):null;
      const key=parseJson('answer_key');
      if(['single_choice','multiple_choice'].includes(input.question_type)) {
        if(!options||typeof options!=='object'||Array.isArray(options)||Object.keys(options).length<2||Object.values(options).some(v=>typeof v!=='string'||!v.trim())) throw new Error(`第 ${line} 行 options：选择题至少需要两个非空选项`);
        const keys=input.question_type==='single_choice'?[key]:key;
        if(!Array.isArray(keys)||!keys.length||keys.some(v=>typeof v!=='string'||!Object.hasOwn(options,v))||new Set(keys).size!==keys.length) throw new Error(`第 ${line} 行 answer_key：必须引用 options 中的选项且不能重复`);
      } else if(input.question_type==='true_false'&&typeof key!=='boolean') throw new Error(`第 ${line} 行 answer_key：判断题必须是 true 或 false`);
      else if(input.question_type==='short_answer'&&(typeof key!=='string'||!key.trim())) throw new Error(`第 ${line} 行 answer_key：简答题需要非空参考答案`);
      else if(input.question_type==='fill_blank'&&!(typeof key==='string'&&key.trim()||Array.isArray(key)&&key.length&&key.every(v=>typeof v==='string'&&v.trim())&&new Set(key).size===key.length)) throw new Error(`第 ${line} 行 answer_key：填空题需要非空答案或答案列表`);
      return {course_id:courseId,question_type:input.question_type,topic:input.topic,stem:input.stem,
        options,answer_key:key,
        explanation:input.explanation||null,max_score:score,
        ...levels};
    }
  });
  if (!items.length || items.length>200) throw new Error('一次需要导入 1～200 道题');
  return items;
}

root.addEventListener('click', async event=>{
  const control=event.target.closest('[data-action]');
  if(!control) return;
  const {action,id,page,tab}=control.dataset;
  try {
    if(action==='auth-tab') {state.authTab=tab;return render();}
    if(action==='toggle-sidebar') {
      state.sidebarCollapsed=!state.sidebarCollapsed;
      saveLogin();
      root.querySelector('.shell')?.classList.toggle('sidebar-collapsed',state.sidebarCollapsed);
      control.setAttribute('aria-expanded',String(!state.sidebarCollapsed));
      control.setAttribute('aria-label',`${state.sidebarCollapsed?'展开':'收起'}侧边栏`);
      control.title=`${state.sidebarCollapsed?'展开':'收起'}侧边栏`;
      control.textContent=state.sidebarCollapsed?'☰':'‹';
      return;
    }
    if(action==='navigate') {state.page=page;return render();}
    if(action==='logout') {Object.assign(state,{token:'',userId:'',role:'',page:'overview',sessionId:'',paper:null,examResult:null});saveLogin();return render();}
    if(action==='refresh') return render();
    if(action==='open-teacher-todo') {
      state.courseId=control.dataset.course;
      state.page=control.dataset.type==='review'?'review':'materials';
      if(state.page==='review') state.reviewAttemptId=id;
      else state.materialId=id;
      return render();
    }
    if(action==='view-plan-wrong'||action==='view-plan-material') {
      const base=`/api/sessions/${enc(state.sessionId)}/plans/${enc(control.dataset.message)}`;
      const item=await api(`${base}/${action==='view-plan-wrong'?'wrong-questions':'materials'}/${enc(id)}`);
      const panel=document.querySelector('#plan-evidence');
      if(!panel) return;
      if(action==='view-plan-wrong') {
        const answer=value=>{
          const values=Array.isArray(value)?value:[value];
          return values.map(v=>`${String(v)}${item.options?.[String(v)]?` · ${item.options[String(v)]}`:''}`).join('、');
        };
        panel.innerHTML=`<div class="card"><div class="row"><h3>错题 ${esc(item.question_id)}</h3><button class="btn small" data-action="close-evidence">关闭</button></div><p>${esc(item.stem)}</p><p>我的答案：${esc(answer(item.student_answer))}</p><p>正确答案：${esc(answer(item.correct_answer))}</p><p>解析：${esc(item.explanation||'暂无解析')}</p></div>`;
      } else panel.innerHTML=`<div class="card"><div class="row"><h3>课程资料 · ${esc(item.source||item.source_title||id)}</h3><button class="btn small" data-action="close-evidence">关闭</button></div><div class="material-text">${esc(item.content)}</div></div>`;
      return;
    }
    if(action==='close-evidence') {const panel=document.querySelector('#plan-evidence');if(panel) panel.innerHTML='';return;}
    if(action==='approve') {await api(`/api/teachers/${enc(id)}/approve`,{method:'POST'});flash('教师账号已批准');return render();}
    if(action==='publish-course') {await api(`/api/courses/admin/${enc(id)}/publish`,{method:'POST'});flash('课程已发布');return render();}
    if(action==='revoke-assignment') {await api(`/api/teachers/${enc(control.dataset.teacher)}/courses/${enc(control.dataset.course)}`,{method:'DELETE'});flash('授权已撤销');return render();}
    if(action==='select-material') {state.materialId=id;state.chunkOffset=0;return render();}
    if(action==='chunks-prev'||action==='chunks-next') {state.chunkOffset=Math.max(0,state.chunkOffset+(action==='chunks-next'?50:-50));return render();}
    if(action==='toggle-compose') {state.composeOpen=!state.composeOpen;return render();}
    if(action==='close-compose') {state.composeOpen=false;return render();}
    if(action==='select-exam') {state.examId=state.examId===id?'':id;return render();}
    if(action==='publish-exam') {
      if(!window.confirm('确认发布这份试卷？发布后学生可以参加考试。')) return;
      await api(`/api/exams/${enc(id)}/publish`,{method:'POST'});flash('试卷已发布');return render();
    }
    if(action==='select-review') {state.reviewAttemptId=id;return render();}
    if(action==='enroll') {await api(`/api/courses/${enc(id)}/enroll`,{method:'POST'});flash('选课成功');return render();}
    if(action==='open-agent') {
      const sessions=await api('/api/sessions');
      let session=sessions.find(s=>s.course_id===id&&s.status==='active');
      if(!session) session=await api('/api/sessions',{method:'POST',body:{course_id:id,title:'课程学习对话'}});
      state.sessionId=session.session_id;state.page='agent';return render();
    }
    if(action==='new-session') {
      const courseId=document.querySelector('[data-select="agent-course"]')?.value;
      if(!courseId) throw new Error('请先选择课程');
      const session=await api('/api/sessions',{method:'POST',body:{course_id:courseId,title:'课程学习对话'}});
      state.courseId=courseId;state.sessionId=session.session_id;return render();
    }
    if(action==='select-session') {state.sessionId=id;return render();}
    if(action==='close-session') {await api(`/api/sessions/${enc(state.sessionId)}/close`,{method:'PATCH'});state.sessionId='';return render();}
    if(action==='start-exam') {
      const attempt=await api(`/api/exams/${enc(id)}/attempts`,{method:'POST'});
      state.attemptId=attempt.attempt_id;state.paper=await api(`/api/exams/attempts/${enc(state.attemptId)}/paper`);state.examResult=null;return render();
    }
    if(action==='resume-exam') {state.attemptId=id;state.paper=await api(`/api/exams/attempts/${enc(id)}/paper`);state.examResult=null;state.page='exams';return render();}
    if(action==='finish-expired-exam') {state.attemptId=id;state.examResult=await api(`/api/exams/attempts/${enc(id)}/submit`,{method:'POST',body:{answers:[]}});state.page='exams';return render();}
    if(action==='open-result') {state.attemptId=id;state.examResult=await api(`/api/exams/attempts/${enc(id)}/result`);state.page='results';return render();}
    if(action==='back-exams') {state.paper=null;state.examResult=null;state.attemptId='';return render();}
    if(action==='refresh-result') {state.examResult=await api(`/api/exams/attempts/${enc(state.attemptId)}/result`);return render();}
    if(action==='download-csv') {
      const url=URL.createObjectURL(new Blob(['\uFEFF',csvTemplate],{type:'text/csv;charset=utf-8'}));
      const link=document.createElement('a');link.href=url;link.download='questions_template.csv';link.click();URL.revokeObjectURL(url);
    }
  } catch(error) {flash(error.message,true);if(!state.token) render();}
});
root.addEventListener('change',event=>{
  const control=event.target;
  if(control.matches('form[data-form="import-questions"] input[name="file"]')) {
    const form=control.closest('form');
    const preview=form.querySelector('[data-import-preview]');
    const status=form.querySelector('[data-import-status]');
    const submit=form.querySelector('[type="submit"]');
    const file=control.files?.[0];
    form.dataset.importValid='false';
    submit.disabled=true;
    submit.title='请先选择有效的 CSV 文件';
    if(!file) {preview.innerHTML='';status.textContent='未选择文件，请先选择 CSV 文件';return;}
    status.textContent=`${file.name} · 正在校验`;
    file.text().then(text=>{
      if(control.files?.[0]!==file) return;
      const items=parseCsv(text,state.courseId);
      const types=Object.entries(items.reduce((counts,item)=>(counts[item.question_type]=(counts[item.question_type]||0)+1,counts),{}));
      preview.innerHTML=`<div class="import-preview"><strong>预览：${items.length} 道题</strong><div class="small muted">${types.map(([type,count])=>`${esc(type)} ${count}`).join(' · ')}</div><div class="table-wrap"><table><thead><tr><th>知识点</th><th>题型</th><th>题干</th></tr></thead><tbody>${items.slice(0,5).map(item=>`<tr><td>${esc(item.topic)}</td><td>${esc(item.question_type)}</td><td>${esc(item.stem)}</td></tr>`).join('')}</tbody></table></div></div>`;
      status.textContent=`${file.name} · 已校验 ${items.length} 道题`;
      form.dataset.importValid='true';
      submit.disabled=false;
      submit.title='';
    }).catch(error=>{if(control.files?.[0]!==file) return;status.textContent=`${file.name} · 校验失败`;preview.innerHTML=`<div class="notice error">${esc(error.message)}</div>`;});
    return;
  }
  if(control.dataset.select==='course') {state.courseId=control.value;state.materialId='';state.examId='';state.reviewAttemptId='';state.chunkOffset=0;state.composeOpen=false;state.questionSearch='';state.selectedQuestions.clear();render();}
  if(control.dataset.select==='agent-course') state.courseId=control.value;
  if(control.dataset.question) {if(control.checked) state.selectedQuestions.add(control.dataset.question);else state.selectedQuestions.delete(control.dataset.question);}
});
root.addEventListener('input',event=>{
  const control=event.target;
  if(!control.matches('[data-question-search]')) return;
  state.questionSearch=control.value;
  const search=control.value.trim().toLocaleLowerCase();
  const rows=[...root.querySelectorAll('[data-question-row]')];
  let count=0;
  rows.forEach(row=>{row.hidden=!row.dataset.search.includes(search);if(!row.hidden) count++;});
  const result=root.querySelector('[data-search-count]');
  if(result) result.textContent=search?`找到 ${count} 道题目`:'全部题目';
});
root.addEventListener('submit',async event=>{
  const form=event.target.closest('form[data-form]');
  if(!form) return;
  event.preventDefault();
  const submit=form.querySelector('[type="submit"]');
  if(submit) submit.disabled=true;
  const data=new FormData(form);
  try {
    switch(form.dataset.form) {
      case 'login': {
        const login=await api('/api/auth/login',{method:'POST',form:new URLSearchParams({username:data.get('user_id').trim(),password:data.get('password')})});
        Object.assign(state,{token:login.access_token,userId:login.user_id,role:login.role,page:login.role==='teacher'?'todo':'overview'});saveLogin();flash('登录成功');break;
      }
      case 'register': {
        const isTeacher=state.authTab==='teacher';
        await api(isTeacher?'/api/auth/register/teacher':'/api/auth/register',{method:'POST',body:{user_id:data.get('user_id').trim(),name:data.get('name').trim(),password:data.get('password')}});
        state.authTab='login';flash(isTeacher?'申请已提交，请等待管理员审核':'注册成功，请登录');break;
      }
      case 'assign-course': {
        await api(`/api/teachers/${enc(data.get('teacher_id').trim())}/courses/${enc(data.get('course_id').trim())}`,{method:'POST'});flash('课程已分配');break;
      }
      case 'create-course': {
        await api('/api/courses',{method:'POST',body:{code:data.get('code').trim(),name:data.get('name').trim(),description:data.get('description').trim()}});
        flash('课程草稿已创建，请确认发布');break;
      }
      case 'upload-material': {
        const file=data.get('file');if(!file?.size) throw new Error('请选择资料文件');if(file.size>20*1024*1024) throw new Error('资料不能超过 20 MB');
        const payload=new FormData();payload.set('file',file);payload.set('title',data.get('title').trim());
        const material=await api(`/api/teacher/course-materials/courses/${enc(state.courseId)}`,{method:'POST',form:payload});
        state.materialId=material.material_id;flash('资料已上传，请查看片段建议并逐段核对');break;
      }
      case 'chunk-topics': {
        const topics=[...new Set(data.get('topics').split(/[,，;；]/).map(s=>s.trim()).filter(Boolean))];
        if(topics.length<1||topics.length>4) throw new Error('每段需要 1～4 个知识点');
        await api(`/api/teacher/course-materials/${enc(state.materialId)}/chunk-topics/${enc(form.dataset.index)}`,{method:'PUT',body:{topics}});
        flash('标签已保存，正在重建索引');break;
      }
      case 'import-questions': {
        const file=data.get('file');if(!file?.size) throw new Error('请选择 CSV 文件');if(file.size>2_000_000) throw new Error('CSV 不能超过 2 MB');
        const items=parseCsv(await file.text(),state.courseId);
        const status=form.querySelector('[data-import-status]');
        if(status) status.textContent=`${file.name} · 正在导入`;
        const result=await api(`/api/teacher/courses/${enc(state.courseId)}/questions/batch`,{method:'POST',body:{items}});
        flash(`已导入 ${result.count} 道题`);break;
      }
      case 'create-exam': {
        const checked=[...form.querySelectorAll('input[data-question]:checked')];
        if(!checked.length) throw new Error('请先勾选题目');
        const items=checked.map(input=>({question_id:input.dataset.question,points:Number(form.querySelector(`[data-points="${CSS.escape(input.dataset.question)}"]`).value)}));
        if(items.some(item=>!Number.isFinite(item.points)||item.points<=0)) throw new Error('题目分值须大于 0');
        const result=await api('/api/exams/drafts',{method:'POST',body:{course_id:state.courseId,title:data.get('title').trim(),duration_minutes:Number(data.get('duration')),items}});
        state.examId=result.exam_id;state.composeOpen=false;state.selectedQuestions.clear();flash('试卷草稿已创建，请预览后发布');break;
      }
      case 'grade-review': {
        const grades=[...form.querySelectorAll('[name^="score-"]')].map(input=>({question_id:input.name.slice(6),score:Number(input.value)}));
        const result=await api(`/api/exams/review/${enc(form.dataset.id)}/grades`,{method:'POST',body:{grades}});
        flash(`批改完成，最终得分 ${money(result.total_score)}`);break;
      }
      case 'chat': {
        const message=data.get('message').trim();if(!message) throw new Error('请输入问题');
        await api('/api/chat',{method:'POST',body:{session_id:state.sessionId,message}});break;
      }
      case 'complete-review-task': {
        const answers=[...form.querySelectorAll('textarea[name^="answer-"]')].map(input=>input.value.trim());
        if(!answers.length||answers.some(answer=>!answer)) throw new Error('请逐题填写自测回答');
        await api(`/api/sessions/${enc(state.sessionId)}/review-tasks/${enc(form.dataset.message)}/${enc(form.dataset.task)}/complete`,{method:'POST',body:{answers}});
        flash('自测已保存，任务已标记完成');break;
      }
      case 'submit-exam': {
        const answers=[...form.querySelectorAll('[data-question-id]')].map(block=>{
          const questionId=block.dataset.questionId,type=block.dataset.type,name=`answer-${questionId}`;
          let answer;
          if(type==='multiple_choice') answer=[...block.querySelectorAll('input:checked')].map(i=>i.value);
          else if(['single_choice','true_false'].includes(type)) {const selected=block.querySelector('input:checked');answer=selected?.value;if(type==='true_false'&&answer!==undefined)answer=answer==='true';}
          else answer=block.querySelector(`[name="${CSS.escape(name)}"]`)?.value.trim();
          if(answer===undefined||answer===''||(Array.isArray(answer)&&!answer.length)) throw new Error(`第 ${block.querySelector('.eyebrow').textContent.replace('QUESTION ','')} 题尚未作答`);
          return {question_id:questionId,answer};
        });
        state.examResult=await api(`/api/exams/attempts/${enc(state.attemptId)}/submit`,{method:'POST',body:{answers}});state.paper=null;flash('试卷已提交');break;
      }
      case 'lookup-result': {
        state.attemptId=data.get('attempt_id');state.examResult=await api(`/api/exams/attempts/${enc(state.attemptId)}/result`);break;
      }
    }
    render();
  } catch(error) {
    flash(error.message,true);
    if(form.dataset.form==='import-questions') {
      const status=form.querySelector('[data-import-status]');
      if(status) status.textContent=`${data.get('file')?.name||'CSV 文件'} · 导入失败`;
    }
    if(!state.token) render();
  }
  finally {if(submit?.isConnected) submit.disabled=form.dataset.form==='import-questions'&&form.dataset.importValid!=='true';}
});

render();
