import { useState, useEffect } from 'react'
import {
  Collapse, Button, Card, Typography, Tag, Table, Space,
  Select, InputNumber, Input, Modal, Timeline, Empty, message,
  Popconfirm, Statistic, Row, Col, Alert,
} from 'antd'
import {
  RocketOutlined, FileTextOutlined, BulbOutlined,
  FlagOutlined, HistoryOutlined, DeleteOutlined,
  PlusOutlined, CloudServerOutlined, ReloadOutlined,
  ExportOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'

const { Text, Paragraph, Title } = Typography

/* ---- 部署面板 ---- */
function DeployPanel({ projectName }) {
  const [platform, setPlatform] = useState('docker')
  const [port, setPort] = useState(8000)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleDeploy = async () => {
    setLoading(true)
    try {
      const res = await api.deployProject(projectName, { platform, port })
      setResult(res)
      message.success(res.message)
    } catch (e) {
      message.error(e.message || '部署文件生成失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <Text style={{ fontSize: 13, minWidth: 60 }}>部署平台</Text>
          <Select
            value={platform} onChange={setPlatform} size="small"
            style={{ width: 160 }}
            options={[
              { label: 'Docker Compose', value: 'docker' },
              { label: 'Vercel', value: 'vercel' },
              { label: 'Railway', value: 'railway' },
            ]}
          />
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <Text style={{ fontSize: 13, minWidth: 60 }}>服务端口</Text>
          <InputNumber value={port} onChange={setPort} size="small" min={1} max={65535} style={{ width: 160 }} />
        </div>
        <Button type="primary" icon={<RocketOutlined />} loading={loading} onClick={handleDeploy} size="small">
          生成部署文件
        </Button>
      </Space>
      {result?.files?.length > 0 && (
        <Card size="small" style={{ marginTop: 12 }}>
          <Text strong>已生成文件：</Text>
          <div style={{ marginTop: 8 }}>
            {result.files.map((f) => <Tag key={f} color="blue">{f}</Tag>)}
          </div>
        </Card>
      )}
      {result && !result.files?.length && (
        <Alert message={result.message || '所有部署文件已存在'} type="info" showIcon style={{ marginTop: 12 }} />
      )}
    </div>
  )
}

/* ---- 文档面板 ---- */
function DocsPanel({ projectName }) {
  const [loading, setLoading] = useState(false)
  const [docResult, setDocResult] = useState(null)

  const handleGenerate = async () => {
    setLoading(true)
    try {
      const res = await api.generateDocs(projectName)
      setDocResult(res)
      message.success(res.message)
    } catch (e) {
      message.error(e.message || '文档生成失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Button type="primary" icon={<FileTextOutlined />} loading={loading} onClick={handleGenerate} size="small">
        生成项目文档
      </Button>
      {docResult?.content && (
        <Card size="small" style={{ marginTop: 12, maxHeight: 400, overflow: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text strong>{docResult.path}</Text>
            {docResult.skipped && <Tag color="warning">已有手写文档</Tag>}
          </div>
          <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'monospace' }}>
            {docResult.content}
          </pre>
        </Card>
      )}
    </div>
  )
}

/* ---- 经验洞察面板 ---- */
function InsightsPanel() {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [keyword, setKeyword] = useState('')

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.fetchInsights(keyword)
      setData(res)
    } catch (e) {
      message.error(e.message || '获取经验失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const columns = [
    { title: '项目', dataIndex: 'project_name', key: 'name', width: 150, ellipsis: true },
    { title: '技术栈', dataIndex: 'tech_stack', key: 'tech', render: (v) => (v || []).slice(0, 3).join(', '), width: 150 },
    { title: '质量', dataIndex: 'quality_score', key: 'quality', width: 60, align: 'center' },
    { title: '状态', dataIndex: 'success', key: 'success', width: 60, align: 'center', render: (v) => v ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag> },
    { title: 'Token', dataIndex: 'total_tokens', key: 'tokens', width: 90, align: 'right', render: (v) => (v || 0).toLocaleString() },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input
          placeholder="输入关键词筛选..."
          size="small" value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={fetchData}
          style={{ width: 200 }}
        />
        <Button icon={<ReloadOutlined />} size="small" loading={loading} onClick={fetchData}>刷新</Button>
      </Space>

      {data?.recommendation && (
        <Alert message={data.recommendation} type="info" showIcon style={{ marginBottom: 12 }} />
      )}
      {data?.avg_tokens > 0 && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          同类项目平均 Token 消耗: {data.avg_tokens.toLocaleString()}
        </Text>
      )}

      <Table
        dataSource={data?.experiences || []}
        columns={columns}
        size="small"
        pagination={false}
        rowKey={(r, i) => r.project_name + i}
        loading={loading}
        locale={{ emptyText: <Empty description="暂无历史经验，运行几个项目后自动积累" /> }}
      />
    </div>
  )
}

/* ---- 里程碑面板 ---- */
function MilestonePanel({ projectName }) {
  const [milestones, setMilestones] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState({ title: '', description: '', version: '' })

  const loadMilestones = async () => {
    try {
      const proj = await api.fetchProject(projectName)
      const meta = proj?.metadata || {}
      setMilestones(meta.milestones || [])
    } catch { /* ignore */ }
  }

  useEffect(() => { loadMilestones() }, [projectName])

  const handleAdd = async () => {
    if (!form.title.trim()) {
      message.warning('标题不能为空')
      return
    }
    setLoading(true)
    try {
      await api.addMilestone(projectName, form)
      message.success('里程碑已添加')
      setModalOpen(false)
      setForm({ title: '', description: '', version: '' })
      loadMilestones()
    } catch (e) {
      message.error(e.message || '添加失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <Text strong>项目里程碑</Text>
        <Button icon={<PlusOutlined />} size="small" onClick={() => setModalOpen(true)}>添加</Button>
      </div>

      {milestones.length > 0 ? (
        <Timeline
          items={milestones.map((m, i) => ({
            color: i === 0 ? 'blue' : 'gray',
            children: (
              <div>
                <Text strong>{m.title}</Text>
                {m.version && <Tag style={{ marginLeft: 8 }}>{m.version}</Tag>}
                {m.description && <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 12 }}>{m.description}</Paragraph>}
                {m.created_at && <Text type="secondary" style={{ fontSize: 11 }}>{new Date(m.created_at).toLocaleString()}</Text>}
              </div>
            ),
          }))}
        />
      ) : (
        <Empty description="暂无里程碑" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}

      <Modal
        title="添加里程碑" open={modalOpen}
        onOk={handleAdd} onCancel={() => setModalOpen(false)}
        okText="添加" cancelText="取消" confirmLoading={loading}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Input placeholder="里程碑标题" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input placeholder="版本号（可选）" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
          <Input.TextArea placeholder="描述（可选）" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Space>
      </Modal>
    </div>
  )
}

/* ---- 会话管理面板 ---- */
function SessionPanel() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(false)

  const loadSessions = async () => {
    setLoading(true)
    try {
      const list = await api.fetchSessions()
      setSessions(list)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { loadSessions() }, [])

  const handleDelete = async (sid) => {
    try {
      await api.deleteSession(sid)
      message.success('会话已删除')
      loadSessions()
    } catch (e) {
      message.error(e.message)
    }
  }

  const handleClearFinished = async () => {
    try {
      const res = await api.clearSessions(true)
      message.success(res.message)
      loadSessions()
    } catch (e) {
      message.error(e.message)
    }
  }

  const handleClearAll = async () => {
    try {
      const res = await api.clearSessions(false)
      message.success(res.message)
      loadSessions()
    } catch (e) {
      message.error(e.message)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'session_id', key: 'id', width: 80, render: (v) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
    { title: '项目', dataIndex: 'project_name', key: 'project', width: 120, ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (v) => {
      const colors = { running: 'processing', completed: 'success', failed: 'error' }
      return <Tag color={colors[v] || 'default'}>{v}</Tag>
    }},
    { title: '需求', dataIndex: 'requirement', key: 'req', ellipsis: true },
    { title: '时间', dataIndex: 'started_at', key: 'time', width: 140, render: (v) => v ? new Date(v * 1000).toLocaleString() : '' },
    { title: '操作', key: 'action', width: 60, render: (_, record) => (
      <Popconfirm title="确定删除?" onConfirm={() => handleDelete(record.session_id)} disabled={record.status === 'running'}>
        <Button type="text" size="small" danger icon={<DeleteOutlined />} disabled={record.status === 'running'} />
      </Popconfirm>
    )},
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <Text strong>会话管理 ({sessions.length})</Text>
        <Space>
          <Button size="small" onClick={loadSessions} icon={<ReloadOutlined />} loading={loading}>刷新</Button>
          <Button size="small" onClick={handleClearFinished}>清理已结束</Button>
          <Popconfirm title="确定清除所有会话？" onConfirm={handleClearAll}>
            <Button size="small" danger>清除全部</Button>
          </Popconfirm>
        </Space>
      </div>
      <Table
        dataSource={sessions}
        columns={columns}
        size="small"
        pagination={{ pageSize: 8, size: 'small' }}
        rowKey="session_id"
        loading={loading}
      />
    </div>
  )
}

/* ---- 模板管理面板 ---- */
function TemplatePanel({ projectName }) {
  const [templates, setTemplates] = useState({ builtin: [], exported: [] })
  const [loading, setLoading] = useState(false)
  const [exportName, setExportName] = useState('')
  const [exportDesc, setExportDesc] = useState('')
  const [exporting, setExporting] = useState(false)

  const loadTemplates = async () => {
    setLoading(true)
    try {
      const res = await api.fetchTemplates()
      setTemplates(res)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { loadTemplates() }, [])

  const handleExport = async () => {
    if (!exportName.trim()) {
      message.warning('请输入模板名称')
      return
    }
    setExporting(true)
    try {
      await api.exportTemplate({
        project_name: projectName,
        template_name: exportName,
        description: exportDesc,
      })
      message.success(`模板已导出: ${exportName}`)
      setExportName('')
      setExportDesc('')
      loadTemplates()
    } catch (e) {
      message.error(e.message || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const allTemplates = [...templates.builtin.map((t) => ({ ...t, type: '内置' })), ...templates.exported.map((t) => ({ ...t, type: '用户导出' }))]

  return (
    <div>
      <Text strong style={{ display: 'block', marginBottom: 12 }}>项目模板 ({allTemplates.length})</Text>
      <Table
        dataSource={allTemplates}
        size="small"
        pagination={false}
        rowKey="id"
        loading={loading}
        columns={[
          { title: 'ID', dataIndex: 'id', key: 'id', width: 120 },
          { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
          { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true },
          { title: '类型', dataIndex: 'type', key: 'type', width: 80, render: (v) => <Tag>{v}</Tag> },
        ]}
        locale={{ emptyText: <Empty description="暂无模板" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
      {projectName && (
        <Card size="small" title={<><ExportOutlined /> 将当前项目导出为模板</>} style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Input placeholder="模板名称" size="small" value={exportName} onChange={(e) => setExportName(e.target.value)} />
            <Input placeholder="模板描述（可选）" size="small" value={exportDesc} onChange={(e) => setExportDesc(e.target.value)} />
            <Button type="primary" size="small" loading={exporting} onClick={handleExport} icon={<ExportOutlined />}>
              导出模板
            </Button>
          </Space>
        </Card>
      )}
    </div>
  )
}

/* ---- 主组件 ---- */
export default function ToolsTab({ projectName }) {
  const theme = useStore((s) => s.theme)
  const isDark = theme === 'dark'

  const items = [
    {
      key: 'deploy',
      label: <span><RocketOutlined /> 部署生成</span>,
      children: <DeployPanel projectName={projectName} />,
    },
    {
      key: 'docs',
      label: <span><FileTextOutlined /> 文档生成</span>,
      children: <DocsPanel projectName={projectName} />,
    },
    {
      key: 'templates',
      label: <span><CloudServerOutlined /> 模板管理</span>,
      children: <TemplatePanel projectName={projectName} />,
    },
    {
      key: 'insights',
      label: <span><BulbOutlined /> 经验洞察</span>,
      children: <InsightsPanel />,
    },
    {
      key: 'milestones',
      label: <span><FlagOutlined /> 里程碑</span>,
      children: <MilestonePanel projectName={projectName} />,
    },
    {
      key: 'sessions',
      label: <span><HistoryOutlined /> 会话管理</span>,
      children: <SessionPanel />,
    },
  ]

  return (
    <div style={{ padding: 16, height: '100%', overflow: 'auto' }}>
      <Collapse
        defaultActiveKey={['deploy']}
        items={items}
        size="small"
        style={{ background: isDark ? '#0d1117' : '#f6f8fa' }}
      />
    </div>
  )
}
