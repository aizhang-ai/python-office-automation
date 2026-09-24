// Markdown 转 HTML 工具自检：用 DOM stub 在 Node 里加载 docs/tools/markdown-html.html 的真实脚本，
// 验证标题、行内语法、代码块、列表、表格、引用、转义与完整文档生成是否真的正确。
// 运行：node tests/tools-mdhtml-selftest.js
'use strict';
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'docs', 'tools', 'markdown-html.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('没找到 script 块'); process.exit(1); }
const code = m[1];

// ---------- DOM stub ----------
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: '', textContent: '', innerHTML: '', className: '', checked: false };
  return els[id];
}
global.document = {
  getElementById: el,
  createElement: function () { return { style: {}, click() {}, remove() {}, href: '', download: '', type: '', accept: '' }; },
  body: { appendChild() {} }
};
try {
  Object.defineProperty(global, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true
  });
} catch (e) { /* Node 内置 navigator 只读，测试不调用剪贴板 */ }
global.Blob = function () {};
global.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };
global.FileReader = function () {};

// ---------- 载入页面脚本 ----------
const api = new Function(code + `
  return { esc, slug, inlineMd, splitRow, isTableSep, mdToHtml, runMd,
           get lastOut(){return lastOut;} };
`)();

let pass = 0, fail = 0;
function check(name, actual, expect) {
  const a = JSON.stringify(actual), e = JSON.stringify(expect);
  if (a === e) { pass++; console.log('  PASS  ' + name); }
  else { fail++; console.log('  FAIL  ' + name + '\n        期望 ' + e + '\n        实际 ' + a); }
}
function has(name, hay, needle) { check(name, String(hay).indexOf(needle) >= 0, true); }

console.log('== 1. HTML 转义 ==');
check('& < > 被转义', api.esc('a&b<c>d'), 'a&amp;b&lt;c&gt;d');
has('行内文本里的 <script> 被吃掉', api.inlineMd('<script>alert(1)</script>'), '&lt;script&gt;');
check('行内代码里的 * 不当语法', api.inlineMd('`a*b*c`'), '<code>a*b*c</code>');

console.log('== 2. 行内语法 ==');
check('粗体', api.inlineMd('**粗**'), '<strong>粗</strong>');
check('斜体', api.inlineMd('a *斜* b'), 'a <em>斜</em> b');
check('删除线', api.inlineMd('~~删~~'), '<del>删</del>');
check('链接', api.inlineMd('[文字](http://x.com)'),
      '<a href="http://x.com" target="_blank" rel="noopener">文字</a>');
check('图片', api.inlineMd('![说明](a.png)'), '<img src="a.png" alt="说明">');
check('粗体+代码混排', api.inlineMd('**粗** 和 `码`'), '<strong>粗</strong> 和 <code>码</code>');

console.log('== 3. 标题与锚点 ==');
let out = api.mdToHtml('# 一级\n## 二级\n### 三级', {});
has('h1', out, '<h1 id="一级">一级</h1>');
has('h2', out, '<h2 id="二级">二级</h2>');
has('h3', out, '<h3 id="三级">三级</h3>');
out = api.mdToHtml('# 标题\n# 标题', {});
const ids = out.match(/id="([^"]+)"/g);
check('重复标题 id 不冲突', ids, ['id="标题"', 'id="标题-1"']); // 第二个同名标题追加 -1
check('三个同名标题递增', (api.mdToHtml('# 甲\n# 甲\n# 甲', {}).match(/id="([^"]+)"/g)), ['id="甲"', 'id="甲-1"', 'id="甲-2"']);
check('七级 # 不当时标题', api.mdToHtml('####### 七个', {}), '<p>####### 七个</p>');

console.log('== 4. 列表 ==');
out = api.mdToHtml('- 一\n- 二\n- 三', {});
check('无序列表', out, '<ul><li>一</li><li>二</li><li>三</li></ul>');
out = api.mdToHtml('1. 甲\n2. 乙', {});
check('有序列表', out, '<ol><li>甲</li><li>乙</li></ol>');
check('* 与 + 也识别', api.mdToHtml('* a\n+ b', {}), '<ul><li>a</li><li>b</li></ul>');

console.log('== 5. 代码块（内部不解析） ==');
out = api.mdToHtml('```python\nprint("**x**")\n```', {});
has('代码块语言类', out, 'class="language-python"');
has('代码块内容保留原文', out, 'print("**x**")');
has('代码块里的 & < > 被转义', api.mdToHtml('```\nif a<b & c>d\n```', {}), 'if a&lt;b &amp; c&gt;d');
check('代码块内不产生 strong', out.indexOf('<strong>') >= 0, false);

console.log('== 6. 表格 ==');
out = api.mdToHtml('| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |', {});
has('表头', out, '<th>A</th><th>B</th>');
has('表体第一行', out, '<tr><td>1</td><td>2</td></tr>');
has('表体第二行', out, '<tr><td>3</td><td>4</td></tr>');
check('表格节点顺序', out.indexOf('</thead>') < out.indexOf('<tbody>'), true);
check('缺分隔符则当普通段落', api.mdToHtml('| A | B |\n| 1 | 2 |', {}).indexOf('<table>') >= 0, false);

console.log('== 7. 引用与分割线 ==');
check('引用', api.mdToHtml('> 注意这一点', {}), '<blockquote>注意这一点</blockquote>');
check('多行引用合成一段', (api.mdToHtml('> 甲\n> 乙', {}).match(/<blockquote>/g) || []).length, 1);
check('引用内勾 nl2br 出 <br>', api.mdToHtml('> 甲\n> 乙', { br: true }), '<blockquote>甲<br>乙</blockquote>');
check('分割线', api.mdToHtml('---', {}), '<hr>');

console.log('== 8. 段落与换行 ==');
check('单换行默认是空格', api.mdToHtml('甲\n乙', {}), '<p>甲 乙</p>');
check('勾了 nl2br 就是 <br>', api.mdToHtml('甲\n乙', { br: true }), '<p>甲<br>乙</p>');
check('空行分段', (api.mdToHtml('甲\n\n乙', {}).match(/<p>/g) || []).length, 2);

console.log('== 9. 完整文档模式 ==');
out = api.mdToHtml('# 标题\n\n正文', { fullDoc: true, title: '我的文档' });
has('含 DOCTYPE', out, '<!DOCTYPE html>');
has('含 title', out, '<title>我的文档</title>');
has('含正文', out, '<h1 id="标题">标题</h1>');
check('以 </html> 收尾', String(out).trim().slice(-7), '</html>');
check('非完整模式不含 DOCTYPE', api.mdToHtml('# 标题', {}).indexOf('<!DOCTYPE') >= 0, false);

console.log('== 10. 边界输入 ==');
check('空输入不报错', api.mdToHtml('', {}), '');
check('null 不报错', api.mdToHtml(null, {}), '');
check('CRLF 归一', api.mdToHtml('# 标题\r\n\r\n正文', {}), '<h1 id="标题">标题</h1>\n<p>正文</p>');
check('只有空行', api.mdToHtml('\n\n\n', {}), '');

console.log('== 11. 端到端：runMd 走真实 DOM 路径 ==');
el('src').value = '# 日报\n\n| 指标 | 值 |\n|---|---|\n| 销售额 | 14112.25 |\n\n- 告警一\n';
el('fulldoc').checked = false;
el('nl2br').checked = false;
const r = api.runMd();
has('出 h1', r, '<h1 id="日报">日报</h1>');
has('出 table', r, '<table>');
has('出 li', r, '<li>告警一</li>');
check('msg 已置为 ok', el('msg').className.indexOf('ok') >= 0, true);
check('lastOut 与返回一致', api.lastOut, r);
el('src').value = '   ';
check('空输入时 runMd 返回 null', api.runMd(), null);

console.log('== 12. 大文档不卡死 ==');
const big = [];
for (let i = 0; i < 2000; i++) big.push('## 小节 ' + i + '\n\n正文 **加粗** 与 `代码`。\n');
const t0 = Date.now();
const bigOut = api.mdToHtml(big.join('\n'), {});
const cost = Date.now() - t0;
check('2000 个小节能出结果', bigOut.length > 1000, true);
check('小节数正确', (bigOut.match(/<h2 /g) || []).length, 2000);
console.log('        （耗时 ' + cost + ' ms）');

console.log('\n通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
