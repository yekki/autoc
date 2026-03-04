export const TECH_STACK_OPTIONS = [
  { label: '后端', options: [
    { label: 'Python', value: 'Python' },
    { label: 'FastAPI', value: 'FastAPI' },
    { label: 'Flask', value: 'Flask' },
    { label: 'Django', value: 'Django' },
    { label: 'Node.js', value: 'Node.js' },
    { label: 'Express', value: 'Express' },
    { label: 'Go', value: 'Go' },
    { label: 'Java', value: 'Java' },
    { label: 'Spring Boot', value: 'Spring Boot' },
    { label: 'Rust', value: 'Rust' },
  ]},
  { label: '前端', options: [
    { label: 'React', value: 'React' },
    { label: 'Vue', value: 'Vue' },
    { label: 'HTML/CSS/JS', value: 'HTML/CSS/JS' },
    { label: 'TypeScript', value: 'TypeScript' },
    { label: 'Next.js', value: 'Next.js' },
    { label: 'Vite', value: 'Vite' },
  ]},
  { label: '数据库', options: [
    { label: 'SQLite', value: 'SQLite' },
    { label: 'PostgreSQL', value: 'PostgreSQL' },
    { label: 'MySQL', value: 'MySQL' },
    { label: 'MongoDB', value: 'MongoDB' },
    { label: 'Redis', value: 'Redis' },
  ]},
  { label: '工具 / 其他', options: [
    { label: 'Docker', value: 'Docker' },
    { label: 'CLI', value: 'CLI' },
    { label: 'Bash', value: 'Bash' },
    { label: 'Jupyter', value: 'Jupyter' },
  ]},
]

// 关键词 → 技术栈映射规则（优先级从高到低匹配）
// 每条规则: keywords 中任意一个命中即触发，tags 为推荐的技术栈
const KEYWORD_RULES = [
  // ── 框架直接命中（最高优先级）──
  { keywords: ['fastapi', 'fast api'],             tags: ['Python', 'FastAPI'] },
  { keywords: ['flask'],                            tags: ['Python', 'Flask'] },
  { keywords: ['django'],                           tags: ['Python', 'Django'] },
  { keywords: ['express'],                          tags: ['Node.js', 'Express'] },
  { keywords: ['next.js', 'nextjs', 'next js'],    tags: ['React', 'TypeScript', 'Next.js'] },
  { keywords: ['spring boot', 'springboot'],        tags: ['Java', 'Spring Boot'] },
  { keywords: ['spring'],                           tags: ['Java', 'Spring Boot'] },
  { keywords: ['vite'],                             tags: ['Vite'] },

  // ── 语言/运行时直接命中 ──
  { keywords: ['python', 'py'],                     tags: ['Python'] },
  { keywords: ['node', 'nodejs', 'node.js'],        tags: ['Node.js'] },
  { keywords: ['golang', 'go语言'],                  tags: ['Go'] },
  { keywords: ['rust'],                             tags: ['Rust'] },
  { keywords: ['java'],                             tags: ['Java'] },
  { keywords: ['typescript', 'ts'],                 tags: ['TypeScript'] },

  // ── 前端框架 ──
  { keywords: ['react'],                            tags: ['React', 'TypeScript'] },
  { keywords: ['vue', 'vuejs'],                     tags: ['Vue', 'TypeScript'] },

  // ── 数据库直接命中 ──
  { keywords: ['postgresql', 'postgres', 'pg'],     tags: ['PostgreSQL'] },
  { keywords: ['mysql'],                            tags: ['MySQL'] },
  { keywords: ['mongodb', 'mongo'],                 tags: ['MongoDB'] },
  { keywords: ['redis'],                            tags: ['Redis'] },
  { keywords: ['sqlite'],                           tags: ['SQLite'] },

  // ── 场景推断（语义匹配）──
  { keywords: ['网站', 'web应用', 'web app', 'webapp', '网页应用'],
    tags: ['Python', 'FastAPI', 'React', 'SQLite'] },
  { keywords: ['前端', 'frontend', '页面', '界面', 'ui'],
    tags: ['React', 'TypeScript', 'Vite'] },
  { keywords: ['后端', 'backend', '服务端', '服务器', 'server'],
    tags: ['Python', 'FastAPI'] },
  { keywords: ['全栈', 'fullstack', 'full stack', 'full-stack'],
    tags: ['Python', 'FastAPI', 'React', 'SQLite'] },
  { keywords: ['api', '接口', 'restful', 'rest api'],
    tags: ['Python', 'FastAPI', 'SQLite'] },
  { keywords: ['微服务', 'microservice'],
    tags: ['Python', 'FastAPI', 'Docker', 'Redis'] },
  { keywords: ['爬虫', 'spider', 'crawler', 'scraper', '抓取'],
    tags: ['Python'] },
  { keywords: ['数据分析', '数据处理', '数据可视化', 'data analysis', 'pandas', 'numpy'],
    tags: ['Python', 'Jupyter'] },
  { keywords: ['机器学习', 'ml', 'ai', '深度学习', '模型训练'],
    tags: ['Python', 'Jupyter'] },
  { keywords: ['命令行', 'cli', '终端工具', '命令行工具'],
    tags: ['Python', 'CLI'] },
  { keywords: ['脚本', 'script', '自动化', 'automation'],
    tags: ['Python', 'Bash'] },
  { keywords: ['游戏', 'game', '小游戏'],
    tags: ['HTML/CSS/JS'] },
  { keywords: ['博客', 'blog', 'cms', '内容管理'],
    tags: ['Python', 'FastAPI', 'React', 'SQLite'] },
  { keywords: ['聊天', 'chat', '即时通讯', 'im', 'websocket'],
    tags: ['Node.js', 'Express', 'React', 'Redis'] },
  { keywords: ['电商', '商城', '购物', 'shop', 'ecommerce'],
    tags: ['Python', 'FastAPI', 'React', 'PostgreSQL', 'Redis'] },
  { keywords: ['管理系统', '后台管理', 'admin', 'dashboard', '仪表盘', '管理平台'],
    tags: ['Python', 'FastAPI', 'React', 'SQLite'] },
  { keywords: ['移动端', 'mobile', 'app', '小程序'],
    tags: ['React', 'TypeScript', 'Node.js'] },
  { keywords: ['docker', '容器', 'container', '部署'],
    tags: ['Docker'] },
  { keywords: ['静态', 'static', '落地页', 'landing'],
    tags: ['HTML/CSS/JS'] },
  { keywords: ['todo', '待办', '任务管理', '记事本', '笔记'],
    tags: ['Python', 'FastAPI', 'React', 'SQLite'] },
  { keywords: ['计算器', 'calculator'],
    tags: ['HTML/CSS/JS'] },
  { keywords: ['文件', '上传', '下载', 'file', 'upload'],
    tags: ['Python', 'FastAPI', 'SQLite'] },
]

/**
 * 基于关键词规则匹配推荐技术栈（纯本地，零延迟）
 * @param {string} description - 需求描述
 * @returns {string[]} 推荐的技术栈标签（去重，最多 6 个）
 */
export function recommendByKeywords(description) {
  if (!description || !description.trim()) return []

  const text = description.toLowerCase()
  const matched = new Set()

  for (const rule of KEYWORD_RULES) {
    if (rule.keywords.some((kw) => text.includes(kw))) {
      rule.tags.forEach((tag) => matched.add(tag))
    }
  }

  // 如果匹配到了前端框架但没有构建工具，自动补 Vite
  const hasFrontend = matched.has('React') || matched.has('Vue')
  const hasBuildTool = matched.has('Vite') || matched.has('Next.js')
  if (hasFrontend && !hasBuildTool) {
    matched.add('Vite')
  }

  // 如果匹配到后端但没数据库，补 SQLite（最轻量）
  const hasBackend = matched.has('FastAPI') || matched.has('Flask') || matched.has('Django')
    || matched.has('Express') || matched.has('Spring Boot')
  const hasDB = matched.has('SQLite') || matched.has('PostgreSQL') || matched.has('MySQL')
    || matched.has('MongoDB')
  if (hasBackend && !hasDB) {
    matched.add('SQLite')
  }

  return [...matched].slice(0, 6)
}
