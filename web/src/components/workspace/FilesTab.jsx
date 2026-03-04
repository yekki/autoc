import { useState } from 'react'
import { Tree, Empty, Spin, Typography, Tag } from 'antd'
import {
  FileOutlined, FolderOutlined, FolderOpenOutlined,
  FileTextOutlined, CodeOutlined, FileMarkdownOutlined,
  FileImageOutlined, Html5Outlined, SettingOutlined,
  DatabaseOutlined, FileExcelOutlined,
} from '@ant-design/icons'
import { Highlight, themes } from 'prism-react-renderer'
import useStore from '../../stores/useStore'
import * as api from '../../services/api'

const { Text } = Typography

const LANG_MAP = {
  py: 'python', js: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
  html: 'html', css: 'css', json: 'json', md: 'markdown', yaml: 'yaml',
  yml: 'yaml', sh: 'bash', sql: 'sql', txt: 'text', toml: 'toml',
  go: 'go', rs: 'rust', java: 'java', rb: 'ruby', php: 'php',
  c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp', cs: 'csharp',
  swift: 'swift', kt: 'kotlin', xml: 'xml', svg: 'xml',
  scss: 'scss', less: 'less', vue: 'markup', svelte: 'markup',
}

// 文件类型 → 图标 + 颜色
const FILE_ICON_MAP = {
  js: { icon: <CodeOutlined />, color: '#f7df1e' },
  jsx: { icon: <CodeOutlined />, color: '#61dafb' },
  ts: { icon: <CodeOutlined />, color: '#3178c6' },
  tsx: { icon: <CodeOutlined />, color: '#3178c6' },
  py: { icon: <CodeOutlined />, color: '#3776ab' },
  html: { icon: <Html5Outlined />, color: '#e34f26' },
  css: { icon: <FileTextOutlined />, color: '#1572b6' },
  scss: { icon: <FileTextOutlined />, color: '#c6538c' },
  json: { icon: <SettingOutlined />, color: '#95a5a6' },
  yaml: { icon: <SettingOutlined />, color: '#cb171e' },
  yml: { icon: <SettingOutlined />, color: '#cb171e' },
  toml: { icon: <SettingOutlined />, color: '#9c4121' },
  md: { icon: <FileMarkdownOutlined />, color: '#083fa1' },
  sql: { icon: <DatabaseOutlined />, color: '#e48e00' },
  go: { icon: <CodeOutlined />, color: '#00add8' },
  rs: { icon: <CodeOutlined />, color: '#dea584' },
  java: { icon: <CodeOutlined />, color: '#b07219' },
  rb: { icon: <CodeOutlined />, color: '#cc342d' },
  php: { icon: <CodeOutlined />, color: '#777bb3' },
  c: { icon: <CodeOutlined />, color: '#555555' },
  cpp: { icon: <CodeOutlined />, color: '#f34b7d' },
  cs: { icon: <CodeOutlined />, color: '#178600' },
  swift: { icon: <CodeOutlined />, color: '#fa7343' },
  kt: { icon: <CodeOutlined />, color: '#a97bff' },
  sh: { icon: <FileTextOutlined />, color: '#89e051' },
  txt: { icon: <FileTextOutlined />, color: '#8b949e' },
  png: { icon: <FileImageOutlined />, color: '#a78bfa' },
  jpg: { icon: <FileImageOutlined />, color: '#a78bfa' },
  svg: { icon: <FileImageOutlined />, color: '#ffb13b' },
  csv: { icon: <FileExcelOutlined />, color: '#217346' },
}

function getFileIcon(filename) {
  const ext = filename.split('.').pop()?.toLowerCase()
  const cfg = FILE_ICON_MAP[ext]
  if (cfg) {
    return <span style={{ color: cfg.color }}>{cfg.icon}</span>
  }
  return <FileOutlined />
}

function getLanguage(filename) {
  const ext = filename.split('.').pop()?.toLowerCase()
  return LANG_MAP[ext] || ext || 'text'
}

function buildFileTree(files) {
  const root = { children: {} }
  for (const filePath of files) {
    const parts = filePath.split('/')
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      if (!current.children[part]) {
        current.children[part] = {
          name: part,
          path: parts.slice(0, i + 1).join('/'),
          isFile: i === parts.length - 1,
          children: {},
        }
      }
      current = current.children[part]
    }
  }
  return root
}

function treeToAntd(node) {
  const entries = Object.values(node.children || {})
  const folders = entries.filter((e) => !e.isFile).sort((a, b) => a.name.localeCompare(b.name))
  const fileNodes = entries.filter((e) => e.isFile).sort((a, b) => a.name.localeCompare(b.name))
  return [...folders, ...fileNodes].map((entry) => {
    const key = entry.path
    if (entry.isFile) {
      return {
        title: entry.name,
        key,
        icon: getFileIcon(entry.name),
        isLeaf: true,
      }
    }
    return {
      title: entry.name,
      key,
      icon: ({ expanded }) => expanded ? <FolderOpenOutlined style={{ color: '#8b949e' }} /> : <FolderOutlined style={{ color: '#8b949e' }} />,
      children: treeToAntd(entry),
    }
  })
}

function CodeViewer({ code, language, isDark }) {
  const prismTheme = isDark ? themes.nightOwl : themes.github
  const lang = language === 'text' ? 'markup' : language
  return (
    <Highlight theme={prismTheme} code={code || '(空文件)'} language={lang}>
      {({ style, tokens, getLineProps, getTokenProps }) => (
        <pre style={{
          ...style,
          margin: 0,
          padding: 12,
          fontSize: 12,
          lineHeight: '20px',
          fontFamily: 'Menlo, Monaco, Consolas, monospace',
          overflow: 'auto',
          minHeight: 200,
          background: 'transparent',
        }}>
          {tokens.map((line, i) => (
            <div key={i} {...getLineProps({ line })} style={{ display: 'flex' }}>
              <span style={{
                display: 'inline-block',
                width: 40,
                textAlign: 'right',
                paddingRight: 12,
                color: isDark ? '#484f58' : '#bbb',
                userSelect: 'none',
                flexShrink: 0,
              }}>
                {i + 1}
              </span>
              <span>
                {line.map((token, key) => (
                  <span key={key} {...getTokenProps({ token })} />
                ))}
              </span>
            </div>
          ))}
        </pre>
      )}
    </Highlight>
  )
}

export default function FilesTab() {
  const theme = useStore((s) => s.theme)
  const files = useStore((s) => s.executionFiles)
  const sessionId = useStore((s) => s.sessionId)
  const selectedProjectName = useStore((s) => s.selectedProjectName)
  const isDark = theme === 'dark'

  const [selectedFile, setSelectedFile] = useState(null)
  const [fileContent, setFileContent] = useState('')
  const [loading, setLoading] = useState(false)

  const treeRoot = buildFileTree(files || [])
  const treeData = treeToAntd(treeRoot)

  const handleSelect = async (keys) => {
    const filePath = keys[0]
    if (!filePath) return

    const isFile = (files || []).includes(filePath)
    if (!isFile) return

    setSelectedFile(filePath)
    setLoading(true)
    try {
      let result
      if (sessionId) {
        result = await api.fetchFile(sessionId, filePath)
      } else if (selectedProjectName) {
        result = await api.fetchProjectFile(selectedProjectName, filePath)
      } else {
        setFileContent('// 无法加载文件：缺少会话或项目信息')
        setLoading(false)
        return
      }
      setFileContent(result.content || '')
    } catch (e) {
      setFileContent(`// 无法加载文件: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  if (!files || files.length === 0) {
    return <Empty description="暂无生成文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <div style={{ display: 'flex', gap: 12, height: 'calc(100vh - 280px)', minHeight: 400 }}>
      <div
        style={{
          width: 220,
          flexShrink: 0,
          overflow: 'auto',
          borderRadius: 6,
          border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          background: isDark ? '#0d1117' : '#fafafa',
          padding: '4px 0',
        }}
      >
        <Tree
          treeData={treeData}
          showIcon
          defaultExpandAll
          onSelect={handleSelect}
          selectedKeys={selectedFile ? [selectedFile] : []}
          style={{ background: 'transparent', fontSize: 12 }}
        />
      </div>

      <div
        style={{
          flex: 1,
          overflow: 'auto',
          borderRadius: 6,
          border: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
          background: isDark ? '#010409' : '#fafafa',
        }}
      >
        {!selectedFile ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: isDark ? '#484f58' : '#bbb',
            fontSize: 13,
          }}>
            选择文件查看内容
          </div>
        ) : loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <Spin />
          </div>
        ) : (
          <div>
            <div style={{
              padding: '6px 12px',
              borderBottom: `1px solid ${isDark ? '#21262d' : '#e8e8e8'}`,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              background: isDark ? '#0d1117' : '#f6f8fa',
            }}>
              {getFileIcon(selectedFile)}
              <Text style={{ fontSize: 12, fontFamily: 'monospace' }}>{selectedFile}</Text>
              <Tag style={{ margin: 0, fontSize: 10 }}>{getLanguage(selectedFile)}</Tag>
            </div>
            <CodeViewer code={fileContent} language={getLanguage(selectedFile)} isDark={isDark} />
          </div>
        )}
      </div>
    </div>
  )
}
