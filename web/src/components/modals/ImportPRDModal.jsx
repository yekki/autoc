import { useState } from 'react'
import { Modal, Input, Form, Upload, message, Typography, Alert } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'

const { Text } = Typography
const { Dragger } = Upload

export default function ImportPRDModal() {
  const open = useStore((s) => s.importPRDOpen)
  const setOpen = useStore((s) => s.setImportPRDOpen)
  const fetchProjects = useStore((s) => s.fetchProjects)
  const selectProject = useStore((s) => s.selectProject)

  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('prd.md')
  const [result, setResult] = useState(null)

  const handleFileRead = (file) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      setContent(e.target.result)
      setFilename(file.name)
    }
    reader.readAsText(file)
    return false
  }

  const handleOk = async () => {
    const values = await form.validateFields()
    const prdContent = content || values.content
    if (!prdContent?.trim()) {
      message.warning('请上传文件或输入 PRD 内容')
      return
    }
    setLoading(true)
    try {
      const res = await api.importPRD({
        content: prdContent,
        filename,
        project_name: values.project_name || '',
      })
      setResult(res)
      message.success(`项目创建成功: ${res.project_name}（${res.task_count} 个任务）`)
      await fetchProjects()
      selectProject(res.folder || res.project_name)
      handleCancel()
    } catch (e) {
      message.error(e.message || '导入失败')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    setOpen(false)
    setContent('')
    setFilename('prd.md')
    setResult(null)
    form.resetFields()
  }

  return (
    <Modal
      title="导入 PRD / 需求文档"
      open={open}
      onOk={handleOk}
      onCancel={handleCancel}
      okText="导入并创建项目"
      cancelText="取消"
      confirmLoading={loading}
      width={640}
      destroyOnHidden
    >
      <Alert
        message="支持 Markdown / Text / JSON 格式，系统将通过 AI 自动解析并拆解为可执行任务"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Form form={form} layout="vertical">
        <Form.Item name="project_name" label="项目名称" tooltip="留空则从文档内容自动推断">
          <Input placeholder="自动推断（可选）" />
        </Form.Item>

        <Dragger
          accept=".md,.txt,.json,.rst,.yaml,.yml"
          beforeUpload={handleFileRead}
          showUploadList={false}
          style={{ marginBottom: 16 }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽上传 PRD 文件</p>
          <p className="ant-upload-hint">支持 .md / .txt / .json / .rst / .yaml 格式</p>
        </Dragger>

        {content && (
          <div style={{ marginBottom: 12 }}>
            <Text type="success">已加载文件: {filename} ({content.length} 字符)</Text>
          </div>
        )}

        <Form.Item name="content" label="或直接输入需求内容">
          <Input.TextArea
            rows={8}
            placeholder="粘贴 PRD 文档内容..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
