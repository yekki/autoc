import { useEffect } from 'react'
import { Table, Tag, Button, Space, Popconfirm, Tooltip, message } from 'antd'
import {
  EyeOutlined, DeleteOutlined, SwapOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

function IntegrityTag({ value }) {
  const map = { ok: { color: 'success', text: '完整' }, warn: { color: 'warning', text: '部分' }, bad: { color: 'error', text: '缺失' } }
  const info = map[value] || map.bad
  return <Tag color={info.color} style={{ margin: 0 }}>{info.text}</Tag>
}

export default function HistoryView() {
  const theme = useStore((s) => s.theme)
  const history = useStore((s) => s.benchmarkHistory)
  const fetchHistory = useStore((s) => s.fetchBenchmarkHistory)
  const fetchDetail = useStore((s) => s.fetchBenchmarkDetail)
  const deleteRun = useStore((s) => s.deleteBenchmarkRun)
  const selectedTags = useStore((s) => s.benchmarkSelectedTags)
  const toggleSelect = useStore((s) => s.toggleBenchmarkSelect)
  const clearSelect = useStore((s) => s.clearBenchmarkSelect)
  const fetchCompare = useStore((s) => s.fetchBenchmarkCompare)
  const isDark = theme === 'dark'

  useEffect(() => { fetchHistory() }, []) // eslint-disable-line

  const handleDelete = async (tag) => {
    try {
      await deleteRun(tag)
      message.success(`已删除: ${tag}`)
    } catch (e) {
      message.error(e.message || '删除失败')
    }
  }

  const handleCompare = () => {
    if (selectedTags.length === 2) {
      fetchCompare(selectedTags[0], selectedTags[1])
      clearSelect()
    }
  }

  const columns = [
    {
      title: '标签',
      dataIndex: 'tag',
      key: 'tag',
      render: (tag) => <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{tag}</span>,
    },
    {
      title: '日期',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 170,
      render: (ts) => ts?.replace('T', ' ').slice(0, 19),
    },
    {
      title: 'Git',
      dataIndex: 'git_commit',
      key: 'git',
      width: 90,
      render: (_, r) => r.git_commit
        ? <code style={{ fontSize: 12 }}>{r.git_commit.slice(0, 7)}{r.git_dirty ? '*' : ''}</code>
        : '-',
    },
    {
      title: '完成率',
      dataIndex: 'completion_rate',
      key: 'rate',
      width: 85,
      sorter: (a, b) => (a.completion_rate || 0) - (b.completion_rate || 0),
      render: (v) => {
        const pct = ((v || 0) * 100).toFixed(0)
        const color = v >= 1 ? 'success' : v >= 0.5 ? 'warning' : 'error'
        return <Tag color={color} style={{ margin: 0 }}>{pct}%</Tag>
      },
    },
    {
      title: '平均 Token',
      dataIndex: 'avg_tokens',
      key: 'tokens',
      width: 105,
      sorter: (a, b) => (a.avg_tokens || 0) - (b.avg_tokens || 0),
      render: (v) => v ? v.toFixed(0) : '-',
    },
    {
      title: '平均耗时',
      dataIndex: 'avg_elapsed',
      key: 'elapsed',
      width: 95,
      sorter: (a, b) => (a.avg_elapsed || 0) - (b.avg_elapsed || 0),
      render: (v) => v ? `${v.toFixed(1)}s` : '-',
    },
    {
      title: '用例数',
      dataIndex: 'case_count',
      key: 'case_count',
      width: 70,
      align: 'center',
      render: (v) => v || '-',
    },
    {
      title: '完整性',
      dataIndex: 'integrity',
      key: 'integrity',
      width: 75,
      render: (v) => <IntegrityTag value={v} />,
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_, r) => (
        <Space size={4}>
          <Tooltip title="查看详情">
            <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => fetchDetail(r.tag)} />
          </Tooltip>
          <Tooltip title={selectedTags.includes(r.tag) ? '取消选中' : '选中对比'}>
            <Button
              type="text" size="small"
              icon={<SwapOutlined />}
              onClick={() => toggleSelect(r.tag)}
              style={selectedTags.includes(r.tag) ? { color: '#58a6ff' } : undefined}
            />
          </Tooltip>
          <Popconfirm title={`删除 ${r.tag}？`} onConfirm={() => handleDelete(r.tag)} okText="删除" cancelText="取消">
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {selectedTags.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
          padding: '8px 16px', borderRadius: 6,
          background: isDark ? '#1c2128' : '#ddf4ff',
          border: `1px solid ${isDark ? '#30363d' : '#54aeff'}`,
        }}>
          <SwapOutlined style={{ color: '#58a6ff' }} />
          <span style={{ fontSize: 13, color: isDark ? '#c9d1d9' : '#1f2328' }}>
            已选中: {selectedTags.join(' vs ')}
          </span>
          <div style={{ flex: 1 }} />
          <Button size="small" type="primary" disabled={selectedTags.length !== 2} onClick={handleCompare}>
            开始对比
          </Button>
          <Button size="small" onClick={clearSelect}>取消</Button>
        </div>
      )}
      <Table
        dataSource={history}
        columns={columns}
        rowKey="tag"
        size="small"
        pagination={{ pageSize: 15, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }}
        style={{
          background: isDark ? '#0d1117' : '#fff',
        }}
      />
    </div>
  )
}
