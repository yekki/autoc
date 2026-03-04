import { useState, useEffect, useCallback } from 'react'
import { Card, Button, Tag, Space, Spin, Empty, Typography, message, Popconfirm } from 'antd'
import { CloudServerOutlined, StopOutlined, ReloadOutlined } from '@ant-design/icons'
import * as api from '../../services/api'
import useStore from '../../stores/useStore'

const { Text, Title } = Typography

export default function SandboxPanel() {
  const theme = useStore((s) => s.theme)
  const isDark = theme === 'dark'
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.fetchSandboxStatus()
      setStatus(data)
    } catch (e) {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const handleStop = async (name) => {
    try {
      await api.stopSandbox(name)
      message.success(`容器 ${name} 已停止`)
      refresh()
    } catch (e) {
      message.error(`停止失败: ${e.message}`)
    }
  }

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
  }

  if (!status || !status.docker_available) {
    return (
      <Empty
        description="Docker 不可用 — 沙箱功能需要 Docker"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        style={{ padding: 40 }}
      />
    )
  }

  const containers = status.containers || []

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <CloudServerOutlined style={{ fontSize: 16, color: isDark ? '#58a6ff' : '#0969da' }} />
          <Text strong>沙箱状态</Text>
          <Tag color="green">已启用</Tag>
          <Tag>{status.sandbox_mode || 'project'} 模式</Tag>
        </Space>
        <Button size="small" icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
      </div>

      {containers.length === 0 ? (
        <Empty description="暂无运行中的沙箱容器" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {containers.map((c) => (
            <Card
              key={c.name}
              size="small"
              style={{ background: isDark ? '#161b22' : '#fafafa', border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}` }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space>
                  <Tag color={c.state === 'running' ? 'green' : 'default'}>{c.state}</Tag>
                  <Text code style={{ fontSize: 12 }}>{c.name}</Text>
                  {c.image && <Text type="secondary" style={{ fontSize: 11 }}>{c.image}</Text>}
                </Space>
                <Popconfirm title="确定停止此容器？" onConfirm={() => handleStop(c.name)} okText="停止" cancelText="取消">
                  <Button size="small" danger icon={<StopOutlined />}>停止</Button>
                </Popconfirm>
              </div>
              {c.ports && (
                <div style={{ marginTop: 6, fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>
                  端口映射: {c.ports}
                </div>
              )}
            </Card>
          ))}
        </Space>
      )}
    </div>
  )
}
