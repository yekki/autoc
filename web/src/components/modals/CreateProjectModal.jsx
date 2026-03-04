import { useState, useEffect } from 'react'
import { Modal, Form, Input, message } from 'antd'
import useStore from '../../stores/useStore'

export default function CreateProjectModal() {
  const createOpen = useStore((s) => s.createProjectOpen)
  const setCreateOpen = useStore((s) => s.setCreateProjectOpen)
  const createProject = useStore((s) => s.createProject)

  const editOpen = useStore((s) => s.editProjectOpen)
  const editTarget = useStore((s) => s.editProjectTarget)
  const closeEditProject = useStore((s) => s.closeEditProject)
  const editProject = useStore((s) => s.editProject)

  const isEditMode = editOpen
  const open = isEditMode ? editOpen : createOpen

  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [folderEdited, setFolderEdited] = useState(false)

  useEffect(() => {
    if (editOpen && editTarget) {
      form.setFieldsValue({
        name: editTarget.name,
        description: editTarget.description,
      })
    }
  }, [editOpen, editTarget, form])

  const handleOk = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      if (isEditMode) {
        await editProject(editTarget.folder || editTarget.name, {
          name: values.name || editTarget.name,
          description: values.description || '',
        })
        message.success('项目已更新')
      } else {
        await createProject({
          name: values.name,
          folder: values.folder || values.name,
          description: values.description || '',
        })
        message.success('项目创建成功')
        form.resetFields()
        setFolderEdited(false)
      }
    } catch (e) {
      if (e.errorFields) return
      message.error(e.message || (isEditMode ? '更新失败' : '创建失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => {
    if (isEditMode) {
      closeEditProject()
    } else {
      setCreateOpen(false)
      form.resetFields()
      setFolderEdited(false)
    }
  }

  const onNameChange = (e) => {
    if (!folderEdited && !isEditMode) {
      form.setFieldValue('folder', e.target.value)
    }
  }

  return (
    <Modal
      title={isEditMode ? `编辑项目：${editTarget?.name}` : '创建项目'}
      open={open}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={isEditMode ? '保存' : '创建'}
      cancelText="取消"
      confirmLoading={loading}
      destroyOnHidden
      forceRender
      okButtonProps={{ 'data-testid': 'project-submit-btn' }}
      cancelButtonProps={{ 'data-testid': 'project-cancel-btn' }}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        {!isEditMode && (
          <>
            <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
              <Input placeholder="例如：我的待办应用" onChange={onNameChange} data-testid="project-name-input" />
            </Form.Item>
            <Form.Item name="folder" label="文件夹名" tooltip="默认与项目名称相同，可自定义" rules={[{ required: true, message: '请输入文件夹名' }]}>
              <Input placeholder="默认与项目名称相同" onChange={() => setFolderEdited(true)} data-testid="project-folder-input" />
            </Form.Item>
          </>
        )}

        {isEditMode && (
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="项目显示名称" data-testid="project-name-input" />
          </Form.Item>
        )}

        <Form.Item name="description" label="项目描述">
          <Input.TextArea rows={3} placeholder="简要描述项目功能和目标（仅显示在首页卡片）" data-testid="project-description-input" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
