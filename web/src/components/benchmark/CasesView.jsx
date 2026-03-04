import { useEffect, useState } from 'react'
import { Table, Tag, Button, Modal, Form, Input, Select, InputNumber, Space, Popconfirm, message, Tooltip } from 'antd'
import { StarFilled, PlusOutlined, EditOutlined, DeleteOutlined, LockOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'

const COMPLEXITY_COLORS = {
  trivial: 'default',
  simple: 'blue',
  medium: 'orange',
  complex: 'red',
}

const COMPLEXITY_OPTIONS = [
  { value: 'trivial', label: 'trivial' },
  { value: 'simple', label: 'simple' },
  { value: 'medium', label: 'medium' },
  { value: 'complex', label: 'complex' },
]

export default function CasesView() {
  const theme = useStore((s) => s.theme)
  const cases = useStore((s) => s.benchmarkCases)
  const fetchCases = useStore((s) => s.fetchBenchmarkCases)
  const createCase = useStore((s) => s.createBenchmarkCase)
  const updateCase = useStore((s) => s.updateBenchmarkCase)
  const deleteCase = useStore((s) => s.deleteBenchmarkCase)
  const isDark = theme === 'dark'

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => { fetchCases() }, []) // eslint-disable-line

  const handleCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ complexity: 'simple', max_iterations: 15, expected_files: '', host_checks: '', runtime_checks: '' })
    setModalOpen(true)
  }

  const handleEdit = (record) => {
    setEditing(record.name)
    form.setFieldsValue({
      ...record,
      expected_files: (record.expected_files || []).join(', '),
      host_checks: '',
      runtime_checks: '',
    })
    setModalOpen(true)
  }

  const handleDelete = async (name) => {
    try {
      await deleteCase(name)
      message.success(`用例 "${name}" 已删除`)
    } catch (e) {
      message.error(e.message || '删除失败')
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload = {
        ...values,
        expected_files: values.expected_files
          ? values.expected_files.split(',').map((s) => s.trim()).filter(Boolean)
          : [],
        host_checks: values.host_checks
          ? values.host_checks.split('\n').map((s) => s.trim()).filter(Boolean)
          : [],
        runtime_checks: values.runtime_checks
          ? values.runtime_checks.split('\n').map((s) => s.trim()).filter(Boolean)
          : [],
      }
      if (editing) {
        await updateCase(editing, payload)
        message.success(`用例 "${payload.name}" 已更新`)
      } else {
        await createCase(payload)
        message.success(`用例 "${payload.name}" 已创建`)
      }
      setModalOpen(false)
    } catch (e) {
      if (e.errorFields) return
      message.error(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, r) => (
        <span style={{ fontWeight: 600 }}>
          {r.is_core && <StarFilled style={{ color: '#d29922', marginRight: 6, fontSize: 12 }} />}
          {name}
          {r.source === 'builtin' && (
            <LockOutlined style={{ color: isDark ? '#484f58' : '#b0b8c1', marginLeft: 6, fontSize: 11 }} />
          )}
        </span>
      ),
    },
    {
      title: '复杂度',
      dataIndex: 'complexity',
      key: 'complexity',
      width: 90,
      render: (v) => <Tag color={COMPLEXITY_COLORS[v] || 'default'} style={{ margin: 0 }}>{v}</Tag>,
    },
    {
      title: '最大迭代',
      dataIndex: 'max_iterations',
      key: 'max_iterations',
      width: 90,
      align: 'center',
    },
    {
      title: '验证项',
      key: 'checks',
      width: 90,
      align: 'center',
      render: (_, r) => {
        const total = (r.expected_files?.length || 0) + (r.host_checks || 0) + (r.runtime_checks || 0)
        return total || '-'
      },
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 80,
      align: 'center',
      render: (v) => (
        <Tag color={v === 'builtin' ? 'default' : 'green'} style={{ margin: 0 }}>
          {v === 'builtin' ? '内置' : '自定义'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      align: 'center',
      render: (_, r) => {
        if (r.source === 'builtin') {
          return <span style={{ color: isDark ? '#484f58' : '#c0c8d0', fontSize: 12 }}>—</span>
        }
        return (
          <Space size={4}>
            <Tooltip title="编辑">
              <Button type="text" size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} />
            </Tooltip>
            <Popconfirm
              title={`确认删除用例 "${r.name}"？`}
              onConfirm={() => handleDelete(r.name)}
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Tooltip title="删除">
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
          <StarFilled style={{ color: '#d29922', marginRight: 4, fontSize: 11 }} />
          标记为核心用例（默认运行）。
          <LockOutlined style={{ marginLeft: 8, marginRight: 4, fontSize: 11 }} />
          内置用例只读，自定义用例支持编辑和删除。
        </div>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleCreate}>
          新建用例
        </Button>
      </div>
      <Table
        dataSource={cases}
        columns={columns}
        rowKey="name"
        size="small"
        pagination={false}
      />

      <Modal
        title={editing ? '编辑用例' : '新建用例'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="用例名称"
            rules={[
              { required: true, message: '请输入用例名称' },
              { pattern: /^[a-zA-Z0-9_-]+$/, message: '只允许字母、数字、下划线和横线' },
            ]}
          >
            <Input placeholder="例如: my_test_case" disabled={!!editing} />
          </Form.Item>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="complexity" label="复杂度" style={{ width: 160 }}>
              <Select options={COMPLEXITY_OPTIONS} />
            </Form.Item>
            <Form.Item name="max_iterations" label="最大迭代" style={{ width: 140 }}>
              <InputNumber min={1} max={100} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="is_core" label="核心用例" valuePropName="checked" style={{ width: 100 }}>
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="简短描述用例功能" maxLength={256} showCount />
          </Form.Item>
          <Form.Item name="expected_files" label="预期文件" tooltip="逗号分隔，例如: app.py, requirements.txt">
            <Input placeholder="app.py, requirements.txt" />
          </Form.Item>
          <Form.Item name="host_checks" label="宿主机检查命令" tooltip="每行一条命令，在宿主机执行">
            <Input.TextArea rows={2} placeholder="每行一条命令，例如:&#10;python -m py_compile app.py" />
          </Form.Item>
          <Form.Item name="runtime_checks" label="运行时检查命令" tooltip="每行一条命令，在容器内执行">
            <Input.TextArea rows={2} placeholder="每行一条命令，例如:&#10;python -c &quot;import app&quot;" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
