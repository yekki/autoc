import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { Button, Card, Input, Tag, Empty, Typography, Tooltip, Dropdown, Checkbox, message, Modal } from 'antd'
import {
  PlusOutlined, SearchOutlined, DeleteOutlined, EditOutlined,
  FolderOutlined, ClockCircleOutlined, CheckCircleFilled,
  SyncOutlined, ExclamationCircleOutlined, EllipsisOutlined,
  RocketOutlined, CodeOutlined, CloseOutlined,
  ThunderboltOutlined, SendOutlined,
} from '@ant-design/icons'
import useStore from '../stores/useStore'
import * as api from '../services/api'

const { Text } = Typography

/** R-015: 将中文/任意显示名称转换为文件系统安全的 ASCII slug */
function toFolderSlug(displayName) {
  if (!displayName) return ''
  const ascii = displayName
    .replace(/\s+/g, '-')
    .replace(/[^a-zA-Z0-9_-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
  if (ascii.length >= 2) return ascii
  // 非 ASCII 字符为主时，用 FNV-1a 无符号哈希生成唯一标识（>>> 0 确保无符号）
  let h = 0x811c9dc5
  for (const c of displayName) {
    h ^= c.charCodeAt(0)
    h = Math.imul(h, 0x01000193)
  }
  return `project-${(h >>> 0).toString(36).slice(0, 6)}`
}

const PROMPT_EXAMPLES = [
  { icon: '🌐', label: 'Web 应用', prompt: '一个带用户登录的 Todo 待办应用，支持增删改查和按状态过滤' },
  { icon: '⚡', label: 'API 服务', prompt: '一个 RESTful 书籍管理 API，支持 CRUD、分页查询和数据验证' },
  { icon: '🖥️', label: '命令行工具', prompt: '一个批量重命名文件的 CLI 工具，支持正则匹配和预览模式' },
  { icon: '🎮', label: '小游戏', prompt: '经典贪吃蛇游戏，键盘方向键控制，吃食物变长，撞墙结束' },
  { icon: '🕷️', label: '爬虫脚本', prompt: '一个网页数据爬取工具，抓取指定 URL 的标题和链接，导出为 CSV' },
  { icon: '📝', label: '个人博客', prompt: '一个简洁的个人博客系统，支持 Markdown 文章发布和分类浏览' },
]

// S-001: 首屏快速启动面板
function QuickStartPanel({ isDark, compact = false }) {
  const quickStart = useStore(s => s.quickStart)
  const recordAiAssistTokens = useStore(s => s.recordAiAssistTokens)
  const quickStartExpanded = useStore(s => s.quickStartExpanded)
  const [displayName, setDisplayName] = useState('')
  const [folderName, setFolderName] = useState('')
  const [folderEdited, setFolderEdited] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [originalRequirement, setOriginalRequirement] = useState('')
  const [polishing, setPolishing] = useState(false)
  const [polishElapsed, setPolishElapsed] = useState(0)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const polishTimerRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (quickStartExpanded && compact && !expanded) {
      setExpanded(true)
      useStore.setState({ quickStartExpanded: false })
      setTimeout(() => inputRef.current?.focus(), 200)
    }
  }, [quickStartExpanded])

  const handleDisplayNameChange = (e) => {
    const val = e.target.value
    setDisplayName(val)
    if (!folderEdited) {
      setFolderName(toFolderSlug(val))
    }
  }

  const handleFolderNameChange = (e) => {
    const val = e.target.value.replace(/\s+/g, '-').replace(/[^a-zA-Z0-9_-]/g, '').toLowerCase()
    setFolderName(val)
    setFolderEdited(true)
  }

  const handlePolish = async () => {
    const t = requirement.trim()
    if (!t) return
    setPolishing(true)
    setPolishElapsed(0)
    setOriginalRequirement(t)
    polishTimerRef.current = setInterval(() => setPolishElapsed(p => p + 1), 1000)
    try {
      const res = await api.aiAssist({
        action: 'polish',
        project_name: folderName || displayName || 'new-project',
        description: t,
      })
      if (res.tokens_used) recordAiAssistTokens(res.tokens_used, 'polish')
      if (res.description) {
        setRequirement(res.description)
        const before = t.length, after = res.description.length
        message.success(`润色完成：${before} → ${after} 字`)
      }
    } catch (e) {
      message.error(e.message || 'AI 润色失败')
      setOriginalRequirement('')
    } finally {
      setPolishing(false)
      clearInterval(polishTimerRef.current)
    }
  }

  const handleExampleClick = (example) => {
    setRequirement(example.prompt)
    if (!displayName.trim()) {
      setDisplayName(example.label)
      if (!folderEdited) setFolderName(toFolderSlug(example.label))
    }
  }

  const handleReset = () => {
    setDisplayName('')
    setFolderName('')
    setFolderEdited(false)
    setRequirement('')
    setOriginalRequirement('')
  }

  const hasFilled = displayName.trim() || requirement.trim()

  const handleSubmit = async () => {
    if (!displayName.trim()) { message.warning('请填写项目名称'); return }
    if (!requirement.trim()) { message.warning('请填写需求描述'); return }
    const effectiveFolder = folderName.trim() || toFolderSlug(displayName.trim())
    if (effectiveFolder.length < 2) { message.warning('文件夹名称太短，请手动填写'); return }
    setLoading(true)
    try {
      await quickStart({
        projectName: effectiveFolder,
        displayName: displayName.trim(),
        requirement: requirement.trim(),
      })
    } catch (e) {
      message.error(e.message || '启动失败')
      setLoading(false)
    }
  }

  const borderColor = isDark ? '#30363d' : '#d0d7de'
  const bg = isDark ? '#161b22' : '#ffffff'
  const accentColor = isDark ? '#58a6ff' : '#0969da'
  const dimColor = isDark ? '#8b949e' : '#656d76'
  const textColor = isDark ? '#c9d1d9' : '#1f2328'

  if (compact && !expanded) {
    return (
      <div
        onClick={() => setExpanded(true)}
        style={{
          padding: '10px 14px', borderRadius: 8,
          border: `1px dashed ${borderColor}`,
          cursor: 'pointer', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 8,
          color: dimColor, fontSize: 13,
          background: isDark ? '#0d1117' : '#f6f8fa',
          transition: 'border-color 0.2s',
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = accentColor}
        onMouseLeave={e => e.currentTarget.style.borderColor = borderColor}
      >
        <RocketOutlined style={{ color: accentColor }} />
        快速新建项目并启动开发...
      </div>
    )
  }

  return (
    <div style={{
      border: `1px solid ${expanded ? (isDark ? '#388bfd66' : '#0969da66') : borderColor}`,
      borderRadius: 10, background: bg, padding: '16px 20px',
      marginBottom: compact ? 16 : 0,
      boxShadow: expanded && !compact ? '0 4px 24px rgba(0,0,0,0.12)' : 'none',
    }}>
      {compact && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: textColor, display: 'flex', alignItems: 'center', gap: 6 }}>
            <RocketOutlined style={{ color: accentColor }} /> 快速启动
          </span>
          <Button size="small" type="text" icon={<CloseOutlined />}
            onClick={() => setExpanded(false)}
            style={{ color: dimColor }}
          />
        </div>
      )}

      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: dimColor, marginBottom: 4 }}>项目名称</div>
        <Input
          ref={inputRef}
          placeholder="番茄钟计时器 / My Project"
          value={displayName}
          onChange={handleDisplayNameChange}
          disabled={loading}
          style={{ background: isDark ? '#0d1117' : '#ffffff', borderColor }}
        />
      </div>
      {/* R-015: 文件夹名（折叠态，仅显示名称包含非 ASCII 时高亮提示） */}
      {displayName && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
            <span style={{ color: dimColor }}>文件夹名：</span>
            <Input
              size="small"
              value={folderName}
              onChange={handleFolderNameChange}
              disabled={loading}
              placeholder="自动生成"
              style={{
                width: 200, fontFamily: 'monospace', fontSize: 11,
                background: isDark ? '#0d1117' : '#f6f8fa',
                borderColor: folderEdited ? (isDark ? '#58a6ff' : '#0969da') : (isDark ? '#30363d' : '#d0d7de'),
                color: isDark ? '#8b949e' : '#656d76',
              }}
            />
            {folderEdited && (
              <Button type="link" size="small"
                style={{ fontSize: 11, height: 18, padding: '0 4px', color: dimColor }}
                onClick={() => { setFolderName(toFolderSlug(displayName)); setFolderEdited(false) }}
              >重置</Button>
            )}
          </div>
        </div>
      )}

      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 11, color: dimColor }}>需求描述</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {originalRequirement && !polishing && requirement !== originalRequirement && (
              <Button
                type="text" size="small"
                onClick={() => { setRequirement(originalRequirement); setOriginalRequirement(''); message.info('已恢复原文') }}
                style={{ fontSize: 11, height: 20, borderRadius: 10, padding: '0 8px', color: dimColor }}
              >
                撤销润色
              </Button>
            )}
            <Tooltip title="AI 润色需求描述">
              <Button
                type="text" size="small" icon={<ThunderboltOutlined />}
                loading={polishing} onClick={handlePolish}
                disabled={!requirement.trim() || loading}
                style={{
                  fontSize: 11, height: 20, borderRadius: 10, padding: '0 8px',
                  color: isDark ? '#a78bfa' : '#7c3aed',
                  background: isDark ? 'rgba(167,139,250,0.08)' : 'rgba(124,58,237,0.06)',
                  border: `1px solid ${isDark ? 'rgba(167,139,250,0.2)' : 'rgba(124,58,237,0.18)'}`,
                }}
              >
                {polishing ? `润色中 ${polishElapsed}s` : '润色'}
              </Button>
            </Tooltip>
          </div>
        </div>
        <Input.TextArea
          value={requirement}
          onChange={e => setRequirement(e.target.value)}
          placeholder="描述你想要构建的软件..."
          autoSize={{ minRows: compact ? 3 : 5, maxRows: 12 }}
          disabled={polishing || loading}
          onKeyDown={e => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault()
              if (!loading && !polishing) handleSubmit()
            }
          }}
          style={{
            fontSize: 13,
            background: isDark ? '#0d1117' : '#ffffff',
            borderColor,
            color: textColor,
          }}
        />
        {!requirement.trim() && !loading && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
            <span style={{ fontSize: 11, color: dimColor, lineHeight: '22px' }}>试试：</span>
            {PROMPT_EXAMPLES.map(ex => (
              <span
                key={ex.label}
                onClick={() => handleExampleClick(ex)}
                style={{
                  fontSize: 11, padding: '2px 10px', borderRadius: 12,
                  cursor: 'pointer', lineHeight: '20px', whiteSpace: 'nowrap',
                  color: isDark ? '#8b949e' : '#656d76',
                  background: isDark ? '#21262d' : '#f6f8fa',
                  border: `1px solid ${isDark ? '#30363d' : '#d0d7de'}`,
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.borderColor = accentColor
                  e.currentTarget.style.color = accentColor
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = isDark ? '#30363d' : '#d0d7de'
                  e.currentTarget.style.color = isDark ? '#8b949e' : '#656d76'
                }}
              >
                {ex.icon} {ex.label}
              </span>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          {hasFilled && !loading && (
            <Button type="text" size="small" onClick={handleReset}
              style={{ fontSize: 12, color: dimColor, padding: '0 6px' }}
            >
              重置
            </Button>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: isDark ? '#484f58' : '#afb8c1' }}>⌘↵ 快速提交</span>
          <Button
            type="primary" icon={<SendOutlined />}
            loading={loading} onClick={handleSubmit}
            disabled={!displayName.trim() || !requirement.trim() || polishing}
          >
            一键启动
          </Button>
        </div>
      </div>
    </div>
  )
}

// spin: true 的状态必须有明确代码路径将其推出，确保执行结束后不会卡在旋转状态
const STATUS_MAP = {
  idle:       { label: '未开始', color: 'default',    spin: false },
  planning:   { label: '规划中', color: 'processing', spin: true  },
  developing: { label: '开发中', color: 'processing', spin: true  },
  testing:    { label: '测试中', color: 'warning',    spin: true  },
  incomplete: { label: '未完成', color: 'warning',    spin: false },
  completed:  { label: '已完成', color: 'success',    spin: false },
  aborted:    { label: '异常终止', color: 'error',    spin: false },
}

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

function ProjectCard({ project, isDark, selectMode, selected, onToggleSelect }) {
  const selectProject = useStore((s) => s.selectProject)
  const deleteProject = useStore((s) => s.deleteProject)
  const openEditProject = useStore((s) => s.openEditProject)


  const status = STATUS_MAP[project.status] || STATUS_MAP.idle
  const techStack = project.tech_stack || []
  const totalTasks = project.total_tasks || 0
  const verifiedTasks = project.verified_tasks || 0

  const menuItems = [
    { key: 'edit', icon: <EditOutlined />, label: '编辑项目' },
    { type: 'divider' },
    { key: 'delete', icon: <DeleteOutlined />, label: '删除项目', danger: true },
  ]

  const onMenuClick = ({ key }) => {
    if (key === 'edit') {
      openEditProject(project)
    } else if (key === 'delete') {
      Modal.confirm({
        title: `删除项目「${project.name}」？`,
        content: '此操作不可撤销，项目文件也会被清除。',
        okText: '删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await deleteProject(project.folder)
            message.success('已删除')
          } catch (e) {
            message.error(e.message || '删除失败')
          }
        },
      })
    }
  }

  const handleClick = () => {
    if (selectMode) {
      onToggleSelect(project.folder)
    } else {
      selectProject(project.folder)
    }
  }

  return (
    <Card
      hoverable
      size="small"
      onClick={handleClick}
      styles={{
        body: { padding: '16px 20px' },
      }}
      style={{
        borderColor: selected ? (isDark ? '#58a6ff' : '#0969da') : (isDark ? '#30363d' : '#d0d7de'),
        background: isDark ? '#161b22' : '#ffffff',
        borderRadius: 8,
        outline: selected ? `2px solid ${isDark ? '#58a6ff' : '#0969da'}` : 'none',
        outlineOffset: -1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          {selectMode ? (
            <Checkbox
              checked={selected}
              onClick={(e) => e.stopPropagation()}
              onChange={() => onToggleSelect(project.folder)}
              style={{ flexShrink: 0 }}
            />
          ) : (
            <FolderOutlined style={{ fontSize: 16, color: isDark ? '#58a6ff' : '#0969da', flexShrink: 0 }} />
          )}
          <span style={{
            fontSize: 15, fontWeight: 600, color: isDark ? '#c9d1d9' : '#1f2328',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {project.name}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <Tag color={status.color} style={{ margin: 0 }}>
            {status.spin
              ? <><SyncOutlined spin style={{ marginRight: 3 }} />{status.label}</>
              : status.label
            }
          </Tag>
          {!selectMode && (
            <Dropdown menu={{ items: menuItems, onClick: onMenuClick }} trigger={['click']}>
              <Button
                type="text" size="small" icon={<EllipsisOutlined />}
                onClick={(e) => e.stopPropagation()}
                style={{ color: isDark ? '#8b949e' : '#656d76' }}
              />
            </Dropdown>
          )}
        </div>
      </div>

      {project.description && (
        <div style={{
          fontSize: 13, color: isDark ? '#8b949e' : '#656d76', marginBottom: 10,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {project.description}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {techStack.slice(0, 4).map((t) => (
          <Tag key={t} style={{ margin: 0, fontSize: 11, borderRadius: 10, padding: '0 8px' }}>{t}</Tag>
        ))}
        {techStack.length > 4 && (
          <Tag style={{ margin: 0, fontSize: 11, borderRadius: 10 }}>+{techStack.length - 4}</Tag>
        )}
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginTop: 10, fontSize: 11, color: isDark ? '#6e7681' : '#8c959f',
      }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {totalTasks > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <CheckCircleFilled style={{ fontSize: 10, color: verifiedTasks >= totalTasks ? '#3fb950' : undefined }} />
              {verifiedTasks}/{totalTasks} 任务
            </span>
          )}
          {project.sessions_count > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <CodeOutlined style={{ fontSize: 10 }} />
              {project.sessions_count} 次执行
            </span>
          )}
        </div>
        <Tooltip title={project.updated_at ? new Date(project.updated_at).toLocaleString('zh-CN') : ''}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <ClockCircleOutlined style={{ fontSize: 10 }} />
            {timeAgo(project.updated_at || project.created_at)}
          </span>
        </Tooltip>
      </div>
    </Card>
  )
}

export default function WelcomePage() {
  const theme = useStore((s) => s.theme)
  const projects = useStore((s) => s.projects)
  const setCreateProjectOpen = useStore((s) => s.setCreateProjectOpen)
  const batchDeleteProjects = useStore((s) => s.batchDeleteProjects)
  const isDark = theme === 'dark'

  const [search, setSearch] = useState('')
  const [selectMode, setSelectMode] = useState(false)
  const [selectedNames, setSelectedNames] = useState(new Set())
  const [batchDeleting, setBatchDeleting] = useState(false)

  const filtered = useMemo(() => {
    if (!search.trim()) return projects
    const q = search.toLowerCase()
    return projects.filter((p) =>
      p.name.toLowerCase().includes(q) ||
      (p.description || '').toLowerCase().includes(q) ||
      (p.tech_stack || []).some((t) => t.toLowerCase().includes(q))
    )
  }, [projects, search])

  const toggleSelect = useCallback((name) => {
    setSelectedNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    if (selectedNames.size === filtered.length) {
      setSelectedNames(new Set())
    } else {
      setSelectedNames(new Set(filtered.map((p) => p.folder)))
    }
  }, [filtered, selectedNames.size])

  const exitSelectMode = useCallback(() => {
    setSelectMode(false)
    setSelectedNames(new Set())
  }, [])

  const enterSelectMode = useCallback(() => {
    setSelectMode(true)
    setSelectedNames(new Set())
  }, [])

  const handleBatchDelete = useCallback(() => {
    const names = [...selectedNames]
    if (names.length === 0) return
    Modal.confirm({
      title: `批量删除 ${names.length} 个项目？`,
      content: '此操作不可撤销，项目文件也会被清除。',
      okText: `删除 ${names.length} 个`,
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setBatchDeleting(true)
        try {
          const result = await batchDeleteProjects(names)
          const deletedCount = result?.deleted_count || 0
          const skippedCount = result?.skipped?.length || 0
          const failedCount = result?.failed?.length || 0
          if (deletedCount > 0) message.success(`已删除 ${deletedCount} 个项目`)
          if (skippedCount > 0) message.warning(`${skippedCount} 个项目正在执行中，已跳过`)
          if (failedCount > 0) message.error(`${failedCount} 个项目删除失败`)
          exitSelectMode()
        } catch (e) {
          message.error(e.message || '批量删除失败')
        } finally {
          setBatchDeleting(false)
        }
      },
    })
  }, [selectedNames, batchDeleteProjects, exitSelectMode])

  if (projects.length === 0) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        minHeight: 'calc(100vh - 48px - 32px - 48px)', padding: '0 16px',
      }}>
        <div style={{ width: '100%', maxWidth: 560 }}>
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🤖</div>
            <h2 style={{ color: isDark ? '#f0f6fc' : '#1f2328', marginBottom: 8, fontSize: 22, fontWeight: 600 }}>
              欢迎使用 AutoC
            </h2>
            <p style={{ color: isDark ? '#8b949e' : '#656d76', fontSize: 14, margin: 0 }}>
              输入项目名和需求，全自动完成代码生成与测试验证
            </p>
          </div>
          <QuickStartPanel isDark={isDark} compact={false} />
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Button type="link" size="small" onClick={() => setCreateProjectOpen(true)}
              style={{ color: isDark ? '#6e7681' : '#8c959f', fontSize: 12 }}>
              或者先创建空项目，稍后填写需求
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '24px 16px' }}>
      {/* S-001: 折叠版快速启动入口 */}
      <QuickStartPanel isDark={isDark} compact />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: isDark ? '#f0f6fc' : '#1f2328' }}>
            我的项目
          </h2>
          <Text type="secondary" style={{ fontSize: 13 }}>
            共 {projects.length} 个项目
          </Text>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {!selectMode ? (
            <>
              <Button icon={<DeleteOutlined />} onClick={enterSelectMode}>批量删除</Button>
            </>
          ) : (
            <>
              <Button size="middle" onClick={toggleSelectAll}>
                {selectedNames.size === filtered.length ? '取消全选' : '全选'}
              </Button>
              <Button
                danger type="primary"
                icon={<DeleteOutlined />}
                disabled={selectedNames.size === 0}
                loading={batchDeleting}
                onClick={handleBatchDelete}
              >
                删除{selectedNames.size > 0 ? ` (${selectedNames.size})` : ''}
              </Button>
              <Button icon={<CloseOutlined />} onClick={exitSelectMode}>取消</Button>
            </>
          )}
        </div>
      </div>

      <Input
        prefix={<SearchOutlined style={{ color: isDark ? '#484f58' : '#afb8c1' }} />}
        placeholder="搜索项目名称、描述或技术栈..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        allowClear
        style={{
          marginBottom: 20, borderRadius: 6,
          background: isDark ? '#0d1117' : '#f6f8fa',
          borderColor: isDark ? '#30363d' : '#d0d7de',
        }}
      />

      {filtered.length > 0 ? (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 12,
        }}>
          {filtered.map((p) => (
            <ProjectCard
              key={p.folder || p.name}
              project={p}
              isDark={isDark}
              selectMode={selectMode}
              selected={selectedNames.has(p.folder)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      ) : (
        <Empty
          description={search ? '没有匹配的项目' : '暂无项目'}
          style={{ padding: '60px 0' }}
        >
          {!search && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateProjectOpen(true)}>
              创建第一个项目
            </Button>
          )}
        </Empty>
      )}
    </div>
  )
}
