import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const root={innerHTML:'',addEventListener(){}};
const toast={append(){}};
const context=vm.createContext({
  document:{querySelector(selector){return selector==='#app'?root:toast;}},
  sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},
  setTimeout,requestAnimationFrame(){},console,
});
vm.runInContext(readFileSync(new URL('./app.js',import.meta.url),'utf8'),context);
assert.match(root.innerHTML,/CoursePilot/);
assert.match(root.innerHTML,/欢迎登录/);
assert.doesNotMatch(root.innerHTML,/TEACH · LEARN · IMPROVE|WELCOME BACK|让每一次测评/);
assert.match(vm.runInContext(`shell()`,context),/data-action="toggle-sidebar"/);
assert.doesNotMatch(vm.runInContext(`shell()`,context),/class="topbar"/);
assert.match(vm.runInContext(`state.sidebarCollapsed=true;shell()`,context),/class="shell sidebar-collapsed"/);
assert.match(vm.runInContext(`shell()`,context),/aria-expanded="false"/);
const parsed=vm.runInContext(`parseCsv('question_type,topic,stem,options,answer_key\\nsingle_choice,列表,下标？,"{""A"":""0"",""B"":""1""}","""A"""\\n','C1')`,context);
assert.equal(parsed.length,1);
assert.equal(parsed[0].answer_key,'A');
assert.equal(parsed[0].course_id,'C1');
const template=vm.runInContext(`parseCsv(csvTemplate,'C1')`,context);
assert.equal(template.length,5);
assert.equal(template[4].question_type,'short_answer');
assert.throws(()=>vm.runInContext(`parseCsv('question_type,topic,stem,answer_key\\nsingle_choice,列表,题干,无效答案\\n','C1')`,context),/CSV|answer_key/);
assert.equal(vm.runInContext(`esc('<script>')`,context),'&lt;script&gt;');

async function renderRole(role, responses, route='overview') {
  const page={innerHTML:'',addEventListener(){}};
  const main={innerHTML:''};
  const ctx=vm.createContext({
    document:{querySelector(selector){return selector==='#app'?page:selector==='#content'?main:toast;}},
    sessionStorage:{getItem(){return JSON.stringify({token:'fixture',userId:'U1',role});},setItem(){},removeItem(){}},
    fetch:async path=>({ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>responses[path]||[]}),
    setTimeout,requestAnimationFrame(){},console,
  });
  vm.runInContext(readFileSync(new URL('./app.js',import.meta.url),'utf8'),ctx);
  vm.runInContext(`state.page=${JSON.stringify(route)}`,ctx);
  await vm.runInContext('render()',ctx);
  return page.innerHTML+main.innerHTML;
}
const teacherResponses={
  '/api/teachers/me/courses':[{course_id:'C1',code:'C1',name:'Python 入门'}],
  '/api/teacher/course-materials/courses/C1/index-status':[],
  '/api/teacher/courses/C1/questions':[],
  '/api/exams/teacher?course_id=C1':[],
  '/api/exams/review/pending?course_id=C1':[],
};
assert.match(await renderRole('teacher',teacherResponses),/data-page="materials"/);
assert.doesNotMatch(await renderRole('teacher',teacherResponses),/data-page="overview"/);
assert.match(await renderRole('student',{'/api/courses':[],'/api/courses/mine':[]}),/class="sidebar"/);
assert.match(await renderRole('student',{'/api/courses':[],'/api/courses/mine':[]}),/data-action="toggle-sidebar"/);
assert.match(await renderRole('teacher',teacherResponses,'materials'),/class="sidebar"/);
assert.match(await renderRole('teacher',teacherResponses,'materials'),/上传资料/);
const questionPage=await renderRole('teacher',teacherResponses,'questions');
assert.match(questionPage,/确认导入/);
assert.match(questionPage,/class="csv-upload-button"/);
assert.match(questionPage,/未选择文件，请先选择 CSV 文件/);
assert.match(questionPage,/确认导入<\/button>/);
assert.match(questionPage,/data-action="toggle-compose" disabled/);
assert.match(questionPage,/class="assessment-columns"/);
assert.match(questionPage,/题库还没有题目/);
assert.match(questionPage,/先导入题目，再创建试卷/);
assert.doesNotMatch(questionPage,/workflow-section-header|试卷预览与发布/);
const populatedResponses={
  ...teacherResponses,
  '/api/teacher/courses/C1/questions':[{question_id:'Q1',question_type:'single_choice',topic:'Python 列表',stem:'列表下标从几开始？',max_score:2}],
  '/api/exams/teacher?course_id=C1':[{exam_id:'E1',title:'单元测验',status:'draft'},{exam_id:'E2',title:'期末测验',status:'published'}],
  '/api/exams/teacher/E1':{exam_id:'E1',duration_minutes:30,total_points:2,questions:[{position:1,stem:'列表下标从几开始？',topic:'Python 列表',points:2}]},
  '/api/exams/teacher/E2':{exam_id:'E2',duration_minutes:60,total_points:2,questions:[{position:1,stem:'列表下标从几开始？',topic:'Python 列表',points:2}]},
};
const populatedPage=await renderRole('teacher',populatedResponses,'questions');
assert.match(populatedPage,/1<\/strong> 道题目/);
assert.match(populatedPage,/2<\/strong> 份试卷/);
assert.match(populatedPage,/1<\/strong> 份已发布/);
assert.match(populatedPage,/data-question-search/);
assert.match(populatedPage,/data-search="列表下标从几开始？ python 列表"/i);
assert.match(populatedPage,/data-action="toggle-compose"/);
assert.doesNotMatch(populatedPage,/data-action="toggle-compose" disabled/);
assert.match(populatedPage,/data-action="publish-exam" data-id="E1"/);
assert.doesNotMatch(populatedPage,/data-action="publish-exam" data-id="E2"/);
assert.match(populatedPage,/单元测验/);
assert.match(populatedPage,/期末测验/);
const noExamPage=await renderRole('teacher',{...populatedResponses,'/api/exams/teacher?course_id=C1':[]},'questions');
assert.match(noExamPage,/点击“创建试卷”，从题库选择题目/);
assert.doesNotMatch(noExamPage,/data-action="toggle-compose" disabled/);
assert.match(await renderRole('teacher',teacherResponses,'review'),/暂无待批改记录/);
assert.match(await renderRole('student',{'/api/courses':[{course_id:'C1',code:'C1',name:'Python 入门'}],'/api/courses/mine':[]}),/加入课程/);
const courseCenter=await renderRole('student',{'/api/courses':[{course_id:'C1',code:'C1',name:'已选课程'},{course_id:'C2',code:'C2',name:'新课程'}],'/api/courses/mine':[{course_id:'C1',code:'C1',name:'已选课程'}]});
assert.equal((courseCenter.match(/<h2>已选课程<\/h2>/g)||[]).length,1);
assert.match(courseCenter,/加入课程/);
const agentPage=await renderRole('student',{'/api/sessions':[],'/api/courses/mine':[]},'agent');
assert.match(agentPage,/学习会话/);
assert.match(agentPage,/<h1>AI 学习助手<\/h1>/);
assert.match(await renderRole('student',{'/api/exams/available':[]},'exams'),/当前没有可参加的考试/);
const attempts=[{attempt_id:7,exam_id:'E1',exam_title:'单元测验',course_id:'C1',course_name:'Python 入门',status:'graded',total_score:8,deadline:'2026-10-22T12:00:00'}];
assert.match(await renderRole('student',{'/api/exams/attempts/mine':attempts},'results'),/单元测验/);
assert.match(await renderRole('student',{'/api/exams/available':[{exam_id:'E1',course_name:'Python 入门',title:'单元测验',duration_minutes:30}],'/api/exams/attempts/mine':attempts},'exams'),/查看成绩/);
assert.match(await renderRole('admin',{'/api/teachers/pending':[],'/api/teachers/assignment-options':{teachers:[],courses:[]}}),/教师注册审核/);
assert.match(await renderRole('admin',{'/api/teachers/pending':[]},'overview'),/data-page="courses"/);
assert.match(await renderRole('admin',{'/api/teachers/pending':[]},'overview'),/data-action="toggle-sidebar"/);
assert.match(await renderRole('admin',{'/api/courses/admin':[]},'courses'),/创建草稿/);
assert.match(await renderRole('admin',{'/api/teachers/assignment-options':{teachers:[{user_id:'T1',name:'教师'}],courses:[{course_id:'C1',code:'C1',name:'Python 入门'}]},'/api/teachers/assignments':[]},'assignments'),/确认分配/);
console.log('Web frontend smoke tests passed.');
