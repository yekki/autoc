import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Drawer, Button, Space, Select, Input, Slider, InputNumber, Switch,
  Card, Row, Col, Tag, message, Tooltip, Tabs, Descriptions, Badge, Typography,
} from 'antd'
import {
  PlusOutlined, CheckCircleFilled, CloseCircleFilled,
  LoadingOutlined, MinusCircleOutlined, ThunderboltOutlined,
  EditOutlined, EyeOutlined, SafetyCertificateOutlined,
  DeleteOutlined, ApiOutlined, RobotOutlined, SettingOutlined,
  GlobalOutlined, KeyOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'

const { Text, Title } = Typography

const AGENTS = [
  { key: 'coder', label: 'Coder AI', desc: '编码实现', icon: '💻' },
  { key: 'critique', label: 'Critique AI', desc: '代码评审', icon: '🔍' },
  { key: 'helper', label: '辅助 AI', desc: '需求优化/咨询等辅助功能', icon: '🤖' },
]

const STATUS_MAP = {
  untested: { icon: <MinusCircleOutlined />, color: '#999', text: '未测试' },
  testing: { icon: <LoadingOutlined />, color: '#1677ff', text: '测试中...' },
  passed: { icon: <CheckCircleFilled />, color: '#52c41a', text: '已通过' },
  failed: { icon: <CloseCircleFilled />, color: '#ff4d4f', text: '未通过' },
}

const DEFAULT_ADVANCED = {
  temperature: 0.7,
  max_tokens: 32768,
  timeout: 120,
  max_rounds: 3,
}

export default function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const setOpen = useStore((s) => s.setSettingsOpen)
  const theme = useStore((s) => s.theme)
  const isDark = theme === 'dark'

  const [mode, setMode] = useState('view')
  const [activeTab, setActiveTab] = useState('credentials')
  const [loading, setLoading] = useState(true)

  const [allProviders, setAllProviders] = useState([])
  const [addedProviders, setAddedProviders] = useState([])
  const [credentials, setCredentials] = useState({})
  const [agentConfig, setAgentConfig] = useState({
    coder: { provider: '', model: '' },
    critique: { provider: '', model: '' },
    helper: { provider: '', model: '' },
  })
  const [testStatus, setTestStatus] = useState({
    coder: 'untested', critique: 'untested', helper: 'untested',
  })
  const [advanced, setAdvanced] = useState({ ...DEFAULT_ADVANCED })
  const [generalSettings, setGeneralSettings] = useState({
    useCnMirror: false,
    enableCritique: true,
  })
  const [saving, setSaving] = useState(false)

  const [savedSnapshot, setSavedSnapshot] = useState(null)

  const configuredAgents = AGENTS.filter(
    (a) => agentConfig[a.key]?.provider && agentConfig[a.key]?.model
  )
  const passedCount = Object.entries(testStatus)
    .filter(([key]) => agentConfig[key]?.provider && agentConfig[key]?.model)
    .filter(([, s]) => s === 'passed').length
  const requiredCount = configuredAgents.length
  const canSave = requiredCount > 0 && passedCount === requiredCount

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setMode('view')
    Promise.all([api.fetchProviders(), api.fetchModelConfig()])
      .then(([provs, config]) => {
        setAllProviders(provs || [])
        _applyConfig(provs || [], config)
      })
      .catch(() => message.error('加载配置失败'))
      .finally(() => setLoading(false))
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const _applyConfig = useCallback((provs, config) => {
    if (!config) return
    const creds = {}
    const added = []
    for (const [pid, cred] of Object.entries(config.credentials || {})) {
      const provInfo = provs.find((p) => p.id === pid)
      if (provInfo) {
        added.push(provInfo)
        creds[pid] = {
          api_key: '',
          api_key_preview: cred.api_key_preview || '',
          has_key: cred.has_key || false,
          base_url: cred.base_url || '',
          verified_models: cred.verified_models || [],
        }
      }
    }
    setAddedProviders(added)
    setCredentials(creds)

    const active = config.active || {}
    const newAgentConfig = {}
    const newTestStatus = {}
    for (const a of AGENTS) {
      const ac = active[a.key] || {}
      newAgentConfig[a.key] = { provider: ac.provider || '', model: ac.model || '' }
      const verified = creds[ac.provider]?.verified_models || []
      newTestStatus[a.key] = verified.includes(ac.model) ? 'passed' : 'untested'
    }
    setAgentConfig(newAgentConfig)
    setTestStatus(newTestStatus)

    if (config.advanced) {
      setAdvanced((prev) => ({ ...prev, ...config.advanced }))
    }

    if (config.general_settings) {
      setGeneralSettings({
        useCnMirror: config.general_settings.use_cn_mirror ?? false,
        enableCritique: config.general_settings.enable_critique ?? false,
      })
    }

    setSavedSnapshot({
      addedProviders: added,
      credentials: creds,
      agentConfig: newAgentConfig,
      advanced: config.advanced || DEFAULT_ADVANCED,
      generalSettings: {
        useCnMirror: config.general_settings?.use_cn_mirror ?? false,
      },
    })
  }, [])

  const enterEditMode = () => setMode('edit')

  const cancelEdit = () => {
    if (savedSnapshot) {
      setAddedProviders(savedSnapshot.addedProviders)
      setCredentials(savedSnapshot.credentials)
      setAgentConfig(savedSnapshot.agentConfig)
      setAdvanced(savedSnapshot.advanced)
      setGeneralSettings(savedSnapshot.generalSettings || { useCnMirror: false })
      const newTestStatus = {}
      for (const a of AGENTS) {
        const ac = savedSnapshot.agentConfig[a.key] || {}
        const verified = savedSnapshot.credentials[ac.provider]?.verified_models || []
        newTestStatus[a.key] = verified.includes(ac.model) ? 'passed' : 'untested'
      }
      setTestStatus(newTestStatus)
    }
    setMode('view')
  }

  const handleAddProvider = (providerId) => {
    const prov = allProviders.find((p) => p.id === providerId)
    if (!prov || addedProviders.find((a) => a.id === providerId)) return
    setAddedProviders((prev) => [...prev, prov])
    setCredentials((prev) => ({
      ...prev,
      [providerId]: { api_key: '', api_key_preview: '', has_key: false, base_url: '', verified_models: [] },
    }))
  }

  const handleRemoveProvider = (providerId) => {
    setAddedProviders((prev) => prev.filter((p) => p.id !== providerId))
    setCredentials((prev) => {
      const next = { ...prev }
      delete next[providerId]
      return next
    })
    setAgentConfig((prev) => {
      const next = { ...prev }
      for (const a of AGENTS) {
        if (next[a.key].provider === providerId) {
          next[a.key] = { provider: '', model: '' }
        }
      }
      return next
    })
    setTestStatus((prev) => {
      const next = { ...prev }
      for (const a of AGENTS) {
        if (agentConfig[a.key].provider === providerId) {
          next[a.key] = 'untested'
        }
      }
      return next
    })
  }

  const handleCredChange = (providerId, field, value) => {
    setCredentials((prev) => ({
      ...prev,
      [providerId]: { ...prev[providerId], [field]: value },
    }))
  }

  const handleAgentChange = (agentKey, field, value) => {
    setAgentConfig((prev) => {
      const next = { ...prev }
      next[agentKey] = { ...next[agentKey], [field]: value }
      if (field === 'provider') next[agentKey].model = ''
      return next
    })
    setTestStatus((prev) => ({ ...prev, [agentKey]: 'untested' }))
  }

  const getModelsForAgent = (agentKey) => {
    const providerId = agentConfig[agentKey]?.provider
    if (!providerId) return []
    const prov = allProviders.find((p) => p.id === providerId)
    if (!prov) return []
    const tagMap = { coder: 'dev', critique: 'dev', helper: 'dev' }
    const tag = tagMap[agentKey]
    return [...prov.models].sort((a, b) => {
      const aHas = (a.tags || []).includes(tag) ? 0 : 1
      const bHas = (b.tags || []).includes(tag) ? 0 : 1
      return aHas - bHas
    })
  }

  const availableProviders = addedProviders.map((p) => ({
    label: p.name, value: p.id,
  }))

  const handleTestAgent = async (agentKey) => {
    const cfg = agentConfig[agentKey]
    if (!cfg.provider || !cfg.model) {
      message.warning('请先选择 Provider 和 Model')
      return
    }
    const cred = credentials[cfg.provider]
    setTestStatus((prev) => ({ ...prev, [agentKey]: 'testing' }))
    try {
      const result = await api.testModel({
        provider: cfg.provider,
        model: cfg.model,
        api_key: cred?.api_key || '',
      })
      if (result.success) {
        setTestStatus((prev) => ({ ...prev, [agentKey]: 'passed' }))
        message.success(`${AGENTS.find((a) => a.key === agentKey)?.label} 模型连接成功`)
      } else {
        setTestStatus((prev) => ({ ...prev, [agentKey]: 'failed' }))
        message.error(result.error || '连接失败')
      }
    } catch (e) {
      setTestStatus((prev) => ({ ...prev, [agentKey]: 'failed' }))
      message.error(e.message || '连接失败')
    }
  }

  const handleTestAll = async () => {
    const toTest = configuredAgents
    if (toTest.length === 0) {
      message.warning('请至少配置一个智能体')
      return
    }
    await Promise.allSettled(toTest.map((a) => handleTestAgent(a.key)))
  }

  const handleSave = async () => {
    if (!canSave) {
      message.warning(`请先测试所有已配置的智能体 (${passedCount}/${requiredCount})`)
      return
    }
    setSaving(true)
    try {
      const credsPayload = {}
      for (const prov of addedProviders) {
        const cred = credentials[prov.id] || {}
        const agentModels = AGENTS
          .filter((a) => agentConfig[a.key].provider === prov.id)
          .map((a) => agentConfig[a.key].model)
          .filter(Boolean)
        const existingModels = cred.verified_models || []
        const allModels = [...new Set([...agentModels, ...existingModels])]
        if (cred.api_key || cred.has_key) {
          credsPayload[prov.id] = {
            api_key: cred.api_key || '',
            base_url: cred.base_url || '',
            models: allModels,
          }
        }
      }
      await api.saveModelConfig({
        active: agentConfig,
        credentials: credsPayload,
        advanced,
        general_settings: {
          use_cn_mirror: generalSettings.useCnMirror,
          enable_critique: generalSettings.enableCritique,
        },
      })
      message.success('配置已保存')
      setMode('view')
      setSavedSnapshot({
        addedProviders: [...addedProviders],
        credentials: { ...credentials },
        agentConfig: { ...agentConfig },
        advanced: { ...advanced },
        generalSettings: { ...generalSettings },
      })
    } catch (e) {
      message.error(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const sectionStyle = {
    background: isDark ? '#161b22' : '#fff',
    borderRadius: 10,
    padding: '20px 24px',
    marginBottom: 20,
    border: `1px solid ${isDark ? '#30363d' : '#e1e4e8'}`,
  }

  const sectionTitleStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
    paddingBottom: 12,
    borderBottom: `1px solid ${isDark ? '#21262d' : '#f0f0f0'}`,
  }

  const labelStyle = {
    fontSize: 12,
    color: isDark ? '#8b949e' : '#656d76',
    marginBottom: 4,
    display: 'block',
  }

  const viewValueStyle = {
    fontSize: 14,
    color: isDark ? '#c9d1d9' : '#1f2328',
    padding: '6px 0',
    minHeight: 32,
    display: 'flex',
    alignItems: 'center',
  }

  const isEditing = mode === 'edit'

  const renderCredentialsSection = () => (
    <div style={sectionStyle}>
      <div style={sectionTitleStyle}>
        <KeyOutlined style={{ fontSize: 18, color: isDark ? '#58a6ff' : '#0969da' }} />
        <Title level={5} style={{ margin: 0 }}>API 凭证</Title>
        {addedProviders.length > 0 && (
          <Tag color="blue" style={{ marginLeft: 'auto' }}>{addedProviders.length} 个服务商</Tag>
        )}
      </div>

      {addedProviders.length === 0 && (
        <div style={{
          textAlign: 'center', padding: '24px 0', color: isDark ? '#484f58' : '#afb8c1',
        }}>
          {isEditing ? '点击下方添加 AI 服务商' : '尚未配置任何 API 凭证'}
        </div>
      )}

      <Row gutter={[12, 12]}>
        {addedProviders.map((prov) => {
          const cred = credentials[prov.id] || {}
          return (
            <Col xs={24} sm={12} key={prov.id}>
              <div
                style={{
                  padding: '14px 16px',
                  borderRadius: 8,
                  background: isDark ? '#0d1117' : '#f6f8fa',
                  border: `1px solid ${isDark ? '#21262d' : '#e1e4e8'}`,
                  height: '100%',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: isEditing ? 12 : 0 }}>
                  <Space>
                    <ApiOutlined style={{ color: isDark ? '#58a6ff' : '#0969da' }} />
                    <Text strong>{prov.name}</Text>
                    {cred.has_key && !cred.api_key && (
                      <Tag color="success" icon={<CheckCircleFilled />}>已配置</Tag>
                    )}
                  </Space>
                  {isEditing && (
                    <Button
                      type="text" size="small" danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleRemoveProvider(prov.id)}
                    >
                      移除
                    </Button>
                  )}
                </div>

                {isEditing ? (
                  <div>
                    <div style={{ marginBottom: 10 }}>
                      <span style={labelStyle}>API Key</span>
                      <Input.Password
                        placeholder={cred.has_key ? `已保存: ${cred.api_key_preview}` : '输入 API Key'}
                        value={cred.api_key}
                        onChange={(e) => handleCredChange(prov.id, 'api_key', e.target.value)}
                        size="middle"
                      />
                    </div>
                    {prov.editable_url && (
                      <div>
                        <span style={labelStyle}>Base URL</span>
                        <Input
                          placeholder="https://..."
                          value={cred.base_url}
                          onChange={(e) => handleCredChange(prov.id, 'base_url', e.target.value)}
                          size="middle"
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ marginBottom: 8 }}>
                      <span style={labelStyle}>API Key</span>
                      <div style={viewValueStyle}>
                        {cred.has_key
                          ? <Text code>{cred.api_key_preview || '******'}</Text>
                          : <Text type="secondary">未设置</Text>
                        }
                      </div>
                    </div>
                    {prov.editable_url && (
                      <div style={{ marginBottom: 8 }}>
                        <span style={labelStyle}>Base URL</span>
                        <div style={viewValueStyle}>
                          {cred.base_url
                            ? <Text code style={{ fontSize: 12 }}>{cred.base_url}</Text>
                            : <Text type="secondary">默认</Text>
                        }
                        </div>
                      </div>
                    )}
                    {cred.verified_models?.length > 0 && (
                      <div>
                        <span style={labelStyle}>已验证模型</span>
                        <Space size={4} wrap>
                          {cred.verified_models.map((m) => (
                            <Tag key={m} color="green" style={{ fontSize: 11 }}>{m}</Tag>
                          ))}
                        </Space>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Col>
          )
        })}
      </Row>

      {isEditing && (() => {
        const unused = allProviders.filter((p) => !addedProviders.find((a) => a.id === p.id))
        if (unused.length === 0) return null
        return (
          <Select
            placeholder="+ 添加服务商"
            style={{ width: '100%', marginTop: 8 }}
            value={null}
            onChange={handleAddProvider}
            options={unused.map((p) => ({ label: p.name, value: p.id }))}
            suffixIcon={<PlusOutlined />}
          />
        )
      })()}
    </div>
  )

  const renderAgentCard = (agent) => {
    const cfg = agentConfig[agent.key]
    const models = getModelsForAgent(agent.key)
    const status = testStatus[agent.key]
    const statusInfo = STATUS_MAP[status]
    const isConfigured = cfg.provider && cfg.model
    const provName = addedProviders.find((p) => p.id === cfg.provider)?.name

    return (
      <Col xs={24} sm={12} key={agent.key}>
        <Card
          size="small"
          style={{
            borderRadius: 10,
            border: `1px solid ${isDark ? '#30363d' : '#e1e4e8'}`,
            background: isDark ? '#0d1117' : '#f6f8fa',
            height: '100%',
          }}
          styles={{ body: { padding: '16px' } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: isDark ? '#21262d' : '#e1e4e8',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 18,
            }}>
              {agent.icon}
            </div>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{agent.label}</div>
              <div style={{ fontSize: 11, color: isDark ? '#8b949e' : '#656d76' }}>{agent.desc}</div>
            </div>
            {isConfigured && (
              <Badge
                status={status === 'passed' ? 'success' : status === 'failed' ? 'error' : 'default'}
                style={{ marginLeft: 'auto' }}
              />
            )}
          </div>

          {isEditing ? (
            <div>
              <div style={{ marginBottom: 10 }}>
                <span style={labelStyle}>服务商</span>
                <Select
                  size="small"
                  style={{ width: '100%' }}
                  placeholder="选择服务商"
                  value={cfg.provider || undefined}
                  onChange={(v) => handleAgentChange(agent.key, 'provider', v)}
                  options={availableProviders}
                  allowClear
                  onClear={() => handleAgentChange(agent.key, 'provider', '')}
                />
              </div>
              <div style={{ marginBottom: 10 }}>
                <span style={labelStyle}>模型</span>
                <Select
                  size="small"
                  style={{ width: '100%' }}
                  placeholder={cfg.provider ? '选择模型' : '先选服务商'}
                  disabled={!cfg.provider}
                  value={cfg.model || undefined}
                  onChange={(v) => handleAgentChange(agent.key, 'model', v)}
                  options={models.map((m) => ({
                    label: (
                      <Space>
                        <span>{m.name || m.id}</span>
                        {(m.tags || []).some((t) => ['dev', 'test'].includes(t)) && (
                          <Tag style={{ fontSize: 10 }} color="blue">推荐</Tag>
                        )}
                      </Space>
                    ),
                    value: m.id,
                  }))}
                />
              </div>
              {isConfigured && (
                <Button
                  size="small"
                  block
                  loading={status === 'testing'}
                  disabled={status === 'testing'}
                  onClick={() => handleTestAgent(agent.key)}
                  style={{ marginTop: 4 }}
                  icon={status === 'passed' ? <CheckCircleFilled style={{ color: '#52c41a' }} /> : undefined}
                >
                  {status === 'testing' ? '测试中...' : status === 'passed' ? '已通过' : '测试连接'}
                </Button>
              )}
              {status === 'failed' && (
                <div style={{ textAlign: 'center', marginTop: 6, fontSize: 12, color: '#ff4d4f' }}>
                  测试未通过，请检查凭证
                </div>
              )}
            </div>
          ) : (
            <div>
              {isConfigured ? (
                <Descriptions column={1} size="small" style={{ marginTop: 0 }}>
                  <Descriptions.Item label="服务商">
                    <Text>{provName || cfg.provider}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="模型">
                    <Text code>{cfg.model}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Space size={4}>
                      <span style={{ color: statusInfo.color }}>{statusInfo.icon}</span>
                      <span style={{ color: statusInfo.color, fontSize: 12 }}>{statusInfo.text}</span>
                    </Space>
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <div style={{
                  textAlign: 'center', padding: '12px 0',
                  color: isDark ? '#484f58' : '#afb8c1', fontSize: 13,
                }}>
                  未配置
                </div>
              )}
            </div>
          )}
        </Card>
      </Col>
    )
  }

  const renderAgentsSection = () => (
    <div style={sectionStyle}>
      <div style={sectionTitleStyle}>
        <RobotOutlined style={{ fontSize: 18, color: isDark ? '#58a6ff' : '#0969da' }} />
        <Title level={5} style={{ margin: 0 }}>智能体模型分配</Title>
        {requiredCount > 0 && (
          <Tag
            color={passedCount === requiredCount ? 'success' : 'warning'}
            style={{ marginLeft: 'auto' }}
          >
            {passedCount}/{requiredCount} 已验证
          </Tag>
        )}
      </div>

      <Row gutter={[14, 14]}>
        {AGENTS.map(renderAgentCard)}
      </Row>

      {isEditing && configuredAgents.length > 1 && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={handleTestAll}
            disabled={configuredAgents.length === 0}
          >
            全部测试
          </Button>
          {!canSave && requiredCount > 0 && (
            <div style={{ fontSize: 12, color: '#faad14', marginTop: 6 }}>
              全部智能体通过测试后方可保存（{passedCount}/{requiredCount}）
            </div>
          )}
        </div>
      )}
    </div>
  )

  const renderAdvancedSection = () => (
    <div style={sectionStyle}>
      <div style={sectionTitleStyle}>
        <SettingOutlined style={{ fontSize: 18, color: isDark ? '#58a6ff' : '#0969da' }} />
        <Title level={5} style={{ margin: 0 }}>高级参数</Title>
      </div>

      {isEditing ? (
        <Row gutter={[24, 16]}>
          <Col span={12}>
            <span style={labelStyle}>温度 (Temperature): {advanced.temperature}</span>
            <Slider
              min={0} max={2} step={0.1}
              value={advanced.temperature}
              onChange={(v) => setAdvanced((p) => ({ ...p, temperature: v }))}
            />
          </Col>
          <Col span={12}>
            <span style={labelStyle}>最大 Token</span>
            <InputNumber
              min={1024} max={128000} step={1024}
              style={{ width: '100%' }}
              value={advanced.max_tokens}
              onChange={(v) => setAdvanced((p) => ({ ...p, max_tokens: v }))}
            />
          </Col>
          <Col span={12}>
            <span style={labelStyle}>超时 (秒)</span>
            <InputNumber
              min={10} max={600} step={10}
              style={{ width: '100%' }}
              value={advanced.timeout}
              onChange={(v) => setAdvanced((p) => ({ ...p, timeout: v }))}
            />
          </Col>
          <Col span={12}>
            <span style={labelStyle}>最大轮次</span>
            <InputNumber
              min={1} max={10} step={1}
              style={{ width: '100%' }}
              value={advanced.max_rounds}
              onChange={(v) => setAdvanced((p) => ({ ...p, max_rounds: v }))}
            />
          </Col>
        </Row>
      ) : (
        <Row gutter={[24, 12]}>
          <Col span={6}>
            <span style={labelStyle}>温度</span>
            <div style={viewValueStyle}>{advanced.temperature}</div>
          </Col>
          <Col span={6}>
            <span style={labelStyle}>最大 Token</span>
            <div style={viewValueStyle}>{advanced.max_tokens?.toLocaleString()}</div>
          </Col>
          <Col span={6}>
            <span style={labelStyle}>超时</span>
            <div style={viewValueStyle}>{advanced.timeout}s</div>
          </Col>
          <Col span={6}>
            <span style={labelStyle}>最大轮次</span>
            <div style={viewValueStyle}>{advanced.max_rounds}</div>
          </Col>
        </Row>
      )}
    </div>
  )

  const renderGeneralSection = () => (
    <div style={sectionStyle}>
      <div style={sectionTitleStyle}>
        <GlobalOutlined style={{ fontSize: 18, color: isDark ? '#58a6ff' : '#0969da' }} />
        <Title level={5} style={{ margin: 0 }}>通用设置</Title>
      </div>

      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 0',
        borderBottom: `1px solid ${isDark ? '#21262d' : '#f0f0f0'}`,
      }}>
        <div>
          <div style={{ fontWeight: 500, fontSize: 14 }}>中国区镜像加速</div>
          <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
            启用后 Agent 安装依赖自动使用国内镜像（pip 清华源 / npm npmmirror / Go goproxy.cn）
          </div>
        </div>
        {isEditing ? (
          <Switch
            checked={generalSettings.useCnMirror}
            onChange={(v) => setGeneralSettings((p) => ({ ...p, useCnMirror: v }))}
          />
        ) : (
          <Tag color={generalSettings.useCnMirror ? 'blue' : 'default'}>
            {generalSettings.useCnMirror ? '已启用' : '未启用'}
          </Tag>
        )}
      </div>

      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 0',
        borderBottom: `1px solid ${isDark ? '#21262d' : '#f0f0f0'}`,
      }}>
        <div>
          <div style={{ fontWeight: 500, fontSize: 14 }}>Critique 评审</div>
          <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', marginTop: 2 }}>
            启用后由独立 Critique Agent 评审代码质量（4 维评分），关闭后仅使用规则型基础评审
          </div>
        </div>
        {isEditing ? (
          <Switch
            checked={generalSettings.enableCritique}
            onChange={(v) => setGeneralSettings((p) => ({ ...p, enableCritique: v }))}
          />
        ) : (
          <Tag color={generalSettings.enableCritique ? 'blue' : 'default'}>
            {generalSettings.enableCritique ? '已启用' : '未启用'}
          </Tag>
        )}
      </div>
    </div>
  )

  const drawerTitle = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <SafetyCertificateOutlined style={{ fontSize: 20, color: isDark ? '#58a6ff' : '#0969da' }} />
      <span style={{ fontSize: 18, fontWeight: 600 }}>系统设置</span>
    </div>
  )

  const drawerFooter = (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 0',
    }}>
      <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
        {isEditing && requiredCount > 0 && (
          <Space>
            <SafetyCertificateOutlined />
            <span>测试通过 {passedCount}/{requiredCount}</span>
          </Space>
        )}
      </div>
      <Space>
        {isEditing ? (
          <>
            <Button onClick={cancelEdit}>取消</Button>
            <Tooltip title={!canSave ? `请先测试全部已配置的智能体 (${passedCount}/${requiredCount})` : ''}>
              <Button
                type="primary"
                loading={saving}
                disabled={!canSave}
                onClick={handleSave}
                icon={<SafetyCertificateOutlined />}
              >
                保存配置
              </Button>
            </Tooltip>
          </>
        ) : (
          <>
            <Button onClick={() => setOpen(false)}>关闭</Button>
            <Button type="primary" icon={<EditOutlined />} onClick={enterEditMode}>
              编辑配置
            </Button>
          </>
        )}
      </Space>
    </div>
  )

  return (
    <Drawer
      title={drawerTitle}
      open={open}
      onClose={() => { if (isEditing) cancelEdit(); setOpen(false); }}
      width={680}
      footer={drawerFooter}
      styles={{
        body: {
          padding: '20px 24px',
          background: isDark ? '#0d1117' : '#f6f8fa',
        },
        header: {
          background: isDark ? '#161b22' : '#fff',
          borderBottom: `1px solid ${isDark ? '#30363d' : '#e1e4e8'}`,
        },
        footer: {
          background: isDark ? '#161b22' : '#fff',
          borderTop: `1px solid ${isDark ? '#30363d' : '#e1e4e8'}`,
        },
      }}
    >
      {isEditing && (
        <div style={{
          marginBottom: 16,
          padding: '10px 14px',
          borderRadius: 8,
          background: isDark ? '#0c2d6b33' : '#ddf4ff',
          border: `1px solid ${isDark ? '#1f6feb44' : '#54aeff66'}`,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
          color: isDark ? '#79c0ff' : '#0969da',
        }}>
          <EditOutlined />
          编辑模式 — 修改后需测试通过才能保存
        </div>
      )}

      {renderCredentialsSection()}
      {renderAgentsSection()}
      {renderAdvancedSection()}
      {renderGeneralSection()}
    </Drawer>
  )
}
