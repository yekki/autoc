import { useState, useCallback, useRef } from 'react'
import Editor, { DiffEditor } from '@monaco-editor/react'
import { Tabs, Button, Space, Tooltip, message, Spin } from 'antd'
import {
  SaveOutlined, UndoOutlined, RedoOutlined,
  FormatPainterOutlined, DiffOutlined, CodeOutlined,
  FullscreenOutlined, FullscreenExitOutlined, CloseOutlined,
} from '@ant-design/icons'
import useStore from '../../stores/useStore'

const LANG_MAP = {
  py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  html: 'html', css: 'css', json: 'json', md: 'markdown', yaml: 'yaml', yml: 'yaml',
  sh: 'shell', sql: 'sql', go: 'go', rs: 'rust', java: 'java', rb: 'ruby', php: 'php',
  c: 'c', cpp: 'cpp', cs: 'csharp', swift: 'swift', xml: 'xml', toml: 'toml',
  scss: 'scss', less: 'less', txt: 'plaintext', cfg: 'ini', ini: 'ini',
}

function detectLanguage(filename) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (filename === 'Dockerfile') return 'dockerfile'
  if (filename === 'Makefile') return 'makefile'
  return LANG_MAP[ext] || 'plaintext'
}

export default function MonacoEditor({
  files = [],
  onSave,
  onClose,
  originalContent,
  readOnly = false,
}) {
  const theme = useStore(s => s.theme)
  const [activeKey, setActiveKey] = useState(files[0]?.path || '')
  const [diffMode, setDiffMode] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [modified, setModified] = useState({})
  const editorRef = useRef(null)

  const activeFile = files.find(f => f.path === activeKey)

  const handleEditorMount = useCallback((editor) => {
    editorRef.current = editor
    editor.addAction({
      id: 'save-file',
      label: '保存文件',
      keybindings: [2048 | 49], // Ctrl+S
      run: () => {
        if (activeFile && onSave) {
          onSave(activeFile.path, editor.getValue())
          message.success(`已保存: ${activeFile.path}`)
          setModified(prev => ({ ...prev, [activeFile.path]: false }))
        }
      },
    })
  }, [activeFile, onSave])

  const handleChange = useCallback((value) => {
    if (activeFile) {
      setModified(prev => ({ ...prev, [activeFile.path]: true }))
    }
  }, [activeFile])

  const handleSave = () => {
    if (editorRef.current && activeFile && onSave) {
      onSave(activeFile.path, editorRef.current.getValue())
      message.success(`已保存: ${activeFile.path}`)
      setModified(prev => ({ ...prev, [activeFile.path]: false }))
    }
  }

  const handleFormat = () => {
    editorRef.current?.getAction('editor.action.formatDocument')?.run()
  }

  const handleUndo = () => editorRef.current?.trigger('', 'undo')
  const handleRedo = () => editorRef.current?.trigger('', 'redo')

  const tabItems = files.map(f => ({
    key: f.path,
    label: (
      <span>
        {f.path.split('/').pop()}
        {modified[f.path] && <span style={{ color: '#faad14', marginLeft: 4 }}>●</span>}
      </span>
    ),
  }))

  const containerStyle = fullscreen
    ? { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 1000, background: theme === 'dark' ? '#1e1e1e' : '#fff' }
    : { height: '100%', display: 'flex', flexDirection: 'column' }

  return (
    <div style={containerStyle}>
      {/* 工具栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '4px 12px', borderBottom: '1px solid var(--border-color)',
        background: theme === 'dark' ? '#252526' : '#f3f3f3',
      }}>
        <Space size={4}>
          {/* Save/Undo/Redo/Format 仅在可编辑模式下显示，readOnly 时完全隐藏 */}
          {readOnly !== true && (
            <>
              <Tooltip title="保存 (Ctrl+S)">
                <Button type="text" size="small" icon={<SaveOutlined />} onClick={handleSave} disabled={!modified[activeKey]} />
              </Tooltip>
              <Tooltip title="撤销">
                <Button type="text" size="small" icon={<UndoOutlined />} onClick={handleUndo} />
              </Tooltip>
              <Tooltip title="重做">
                <Button type="text" size="small" icon={<RedoOutlined />} onClick={handleRedo} />
              </Tooltip>
              <Tooltip title="格式化">
                <Button type="text" size="small" icon={<FormatPainterOutlined />} onClick={handleFormat} />
              </Tooltip>
            </>
          )}
          <Tooltip title={diffMode ? '编辑模式' : 'Diff 对比'}>
            <Button
              type="text" size="small"
              icon={diffMode ? <CodeOutlined /> : <DiffOutlined />}
              onClick={() => setDiffMode(!diffMode)}
              disabled={!originalContent}
            />
          </Tooltip>
        </Space>
        <Space size={4}>
          <Tooltip title={fullscreen ? '退出全屏' : '全屏'}>
            <Button type="text" size="small"
              icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={() => setFullscreen(!fullscreen)}
            />
          </Tooltip>
          {onClose && (
            <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
          )}
        </Space>
      </div>

      {/* 标签页 */}
      {files.length > 1 && (
        <Tabs
          type="card" size="small"
          activeKey={activeKey}
          onChange={setActiveKey}
          items={tabItems}
          style={{ margin: 0, padding: '0 8px' }}
          tabBarStyle={{ marginBottom: 0 }}
        />
      )}

      {/* 编辑器 */}
      <div style={{ flex: 1, minHeight: 0 }}>
        {activeFile ? (
          diffMode && originalContent ? (
            <DiffEditor
              original={originalContent}
              modified={activeFile.content || ''}
              language={detectLanguage(activeFile.path)}
              theme={theme === 'dark' ? 'vs-dark' : 'light'}
              options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false } }}
            />
          ) : (
            <Editor
              value={activeFile.content || ''}
              language={detectLanguage(activeFile.path)}
              theme={theme === 'dark' ? 'vs-dark' : 'light'}
              onMount={handleEditorMount}
              onChange={handleChange}
              loading={<Spin description="加载编辑器..." />}
              options={{
                readOnly,
                minimap: { enabled: files.length <= 1 },
                fontSize: 13,
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                renderWhitespace: 'selection',
                unicodeHighlight: {
                  ambiguousCharacters: false,
                  invisibleCharacters: false,
                  nonBasicASCII: false,
                },
              }}
            />
          )
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#999' }}>
            选择文件开始编辑
          </div>
        )}
      </div>
    </div>
  )
}
