import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Tree, Button, Tooltip, Badge, Empty, Spin, message } from 'antd'
import { ReloadOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons'
import useStore from '../../stores/useStore'
import MonacoEditor from '../code/MonacoEditor'
import * as api from '../../services/api'
import { buildFileTree } from './helpers'

/**
 * 代码 Tab — 文件树 + Monaco 编辑器（支持可编辑模式 + Ctrl+S 保存）
 */
export default function CodeTab({ projectName, workspaceFiles }) {
  const theme = useStore(s => s.theme)
  const isDark = theme === 'dark'
  const newlyCreatedFiles = useStore(s => s.newlyCreatedFiles) || []
  const setExecutionPlanMd = useStore(s => s.setExecutionPlanMd)

  const [selectedFile, setSelectedFile] = useState(null)
  const [fileContent, setFileContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')   // Diff 基准：最后一次保存的内容
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [files, setFiles] = useState(workspaceFiles)
  const [prevNewCount, setPrevNewCount] = useState(0)
  const [editMode, setEditMode] = useState(false)

  // 文件树宽度拖拽
  const STORAGE_KEY = 'autoc-codetab-tree-width'
  const [treeWidth, setTreeWidth] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? Math.max(160, Math.min(600, Number(saved))) : 240
  })
  const draggingRef = useRef(false)
  const startXRef = useRef(0)
  const startWidthRef = useRef(0)

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return
      const delta = e.clientX - startXRef.current
      const next = Math.max(160, Math.min(600, startWidthRef.current + delta))
      setTreeWidth(next)
    }
    const onUp = () => {
      if (draggingRef.current) {
        draggingRef.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        setTreeWidth(w => { localStorage.setItem(STORAGE_KEY, String(w)); return w })
      }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [])

  const handleResizeStart = useCallback((e) => {
    e.preventDefault()
    draggingRef.current = true
    startXRef.current = e.clientX
    startWidthRef.current = treeWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [treeWidth])

  // 同步外部传入的文件列表
  useEffect(() => {
    setFiles(workspaceFiles)
    if (!workspaceFiles || workspaceFiles.length === 0) {
      setSelectedFile(null)
      setFileContent('')
      setOriginalContent('')
    }
  }, [workspaceFiles])

  // 新文件创建时自动选中最新文件
  useEffect(() => {
    if (newlyCreatedFiles.length > prevNewCount) {
      const latest = newlyCreatedFiles[newlyCreatedFiles.length - 1]
      setPrevNewCount(newlyCreatedFiles.length)
      if (latest && files.includes(latest)) {
        setSelectedFile(latest)
        setLoading(true)
        api.fetchProjectFile(projectName, latest)
          .then(res => {
            const c = res.content ?? ''
            setFileContent(c)
            setOriginalContent(c)
          })
          .catch(e => setFileContent(`// 无法加载文件: ${e.message}`))
          .finally(() => setLoading(false))
      }
    }
  }, [newlyCreatedFiles, files, projectName, prevNewCount])

  const newFileSet = useMemo(() => new Set(newlyCreatedFiles), [newlyCreatedFiles])

  // 为新文件添加 NEW badge
  const addNewBadge = useCallback((nodes) => {
    return nodes.map(node => {
      const patched = { ...node }
      if (node.isLeaf && newFileSet.has(node.key)) {
        patched.title = (
          <span>
            {node.title}{' '}
            <Badge count="NEW" size="small" style={{ backgroundColor: '#3fb950', fontSize: 9, marginLeft: 4 }} />
          </span>
        )
      }
      if (node.children?.length) {
        patched.children = addNewBadge(node.children)
      }
      return patched
    })
  }, [newFileSet])

  const rawTree = useMemo(() => buildFileTree(files), [files])
  const treeData = useMemo(() => addNewBadge(rawTree), [rawTree, addNewBadge])

  // 选中文件，加载内容
  const handleSelect = useCallback(async (keys) => {
    if (!keys.length) return
    const path = keys[0]
    if (!files.includes(path)) return
    setSelectedFile(path)
    setEditMode(false)
    setLoading(true)
    try {
      const res = await api.fetchProjectFile(projectName, path)
      const c = res.content ?? ''
      setFileContent(c)
      setOriginalContent(c)
    } catch (e) {
      setFileContent(`// 无法加载文件: ${e.message}`)
      setOriginalContent('')
    } finally {
      setLoading(false)
    }
  }, [files, projectName])

  // 刷新文件列表
  const handleRefresh = useCallback(async () => {
    try {
      const p = await api.fetchProject(projectName)
      if (p?.workspace_files) setFiles(p.workspace_files)
    } catch { /* ignore */ }
  }, [projectName])

  // 保存文件（写回工作区）
  const handleSave = useCallback(async (path, content) => {
    setSaving(true)
    try {
      await api.saveProjectFile(projectName, path, content)
      setOriginalContent(content)
      setFileContent(content)
      // 若保存的是 PLAN.md，同步更新概览页的展示内容
      if (path === 'PLAN.md' && setExecutionPlanMd) {
        setExecutionPlanMd(content)
      }
      message.success(`已保存: ${path}`)
    } catch (e) {
      message.error(`保存失败: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }, [projectName, setExecutionPlanMd])

  const borderColor = isDark ? '#30363d' : '#d0d7de'

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* 文件树 */}
      <div style={{ width: treeWidth, flexShrink: 0, overflow: 'auto' }}>
        <div style={{
          padding: '8px 12px', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', borderBottom: `1px solid ${borderColor}`,
        }}>
          <span style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76' }}>
            文件
            {newlyCreatedFiles.length > 0 && <Badge count={newlyCreatedFiles.length} size="small" style={{ marginLeft: 6 }} />}
          </span>
          <Tooltip title="刷新文件列表">
            <Button type="text" size="small" icon={<ReloadOutlined />} onClick={handleRefresh} />
          </Tooltip>
        </div>
        {treeData.length > 0 ? (
          <Tree
            showIcon treeData={treeData} onSelect={handleSelect}
            selectedKeys={selectedFile ? [selectedFile] : []}
            defaultExpandAll style={{ padding: 8 }}
          />
        ) : (
          <Empty description="暂无文件" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
        )}
      </div>

      {/* 拖拽分隔条 */}
      <div
        className="codetab-resize-handle"
        onMouseDown={handleResizeStart}
        style={{
          width: 4, flexShrink: 0, cursor: 'col-resize',
          background: borderColor, position: 'relative',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = isDark ? '#58a6ff' : '#0969da'}
        onMouseLeave={e => { if (!draggingRef.current) e.currentTarget.style.background = borderColor }}
      />

      {/* 编辑器区域 */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* 编辑/预览切换 */}
        {selectedFile && !loading && (
          <div style={{
            padding: '4px 12px', borderBottom: `1px solid ${borderColor}`,
            background: isDark ? '#161b22' : '#f6f8fa',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 12, color: isDark ? '#8b949e' : '#656d76', fontFamily: 'monospace' }}>
              {selectedFile}
            </span>
            <Tooltip title={editMode ? '切换为只读模式' : '切换为编辑模式'}>
              <Button
                type={editMode ? 'primary' : 'default'}
                size="small"
                icon={editMode ? <EyeOutlined /> : <EditOutlined />}
                onClick={() => setEditMode(v => !v)}
                loading={saving}
              >
                {editMode ? '预览' : '编辑'}
              </Button>
            </Tooltip>
          </div>
        )}

        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
            <Spin tip="加载文件..." />
          </div>
        ) : selectedFile ? (
          <div style={{ flex: 1, minHeight: 0 }}>
            <MonacoEditor
              files={[{ path: selectedFile, content: fileContent }]}
              readOnly={!editMode}
              onSave={editMode ? handleSave : undefined}
              originalContent={originalContent !== fileContent ? originalContent : undefined}
            />
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
            <Empty description="选择左侧文件开始浏览" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          </div>
        )}
      </div>
    </div>
  )
}
