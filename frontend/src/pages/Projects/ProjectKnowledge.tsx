import { useParams, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import Topbar from '../../components/Shell/Topbar'
import MarkdownViewer from '../../components/MarkdownViewer/MarkdownViewer'
import { getProject, getProjectKnowledge } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import type { TranslationKey } from '../../i18n'
import './ProjectKnowledge.css'

interface KnowledgeFile {
  name: string
  type: string
  content: string
}

const SKILL_KEYS: Record<string, TranslationKey> = {
  'project.md': 'knowledge.project_md',
  'backend-structure': 'knowledge.backend_structure',
  'frontend-structure': 'knowledge.frontend_structure',
  'business-flow': 'knowledge.business_flow',
  'component-usage': 'knowledge.component_usage',
  'module-overview': 'knowledge.module_overview',
  'api-interaction': 'knowledge.api_interaction',
  'data-entity': 'knowledge.data_entity',
  dependencies: 'knowledge.dependencies',
}

export default function ProjectKnowledge() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [projectName, setProjectName] = useState('')
  const [files, setFiles] = useState<KnowledgeFile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!projectId) return
    getProject(projectId).then(p => setProjectName(p.name)).catch(() => {})
    getProjectKnowledge(projectId)
      .then(data => {
        setFiles(data.files)
        if (data.files.length > 0) setSelected(data.files[0].name)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [projectId])

  const selectedFile = files.find(f => f.name === selected)

  return (
    <>
      <Topbar
        title={projectName || 'Project'}
        subtitle={t('kb.subtitle')}
        backTo="/projects"
        backLabel={t('nav.projects')}
      />
      <div className="content kb-page">
        <div className="kb-sidebar">
          <div className="kb-sidebar-title">{t('kb.sidebar_title')}</div>
          {loading && <div className="kb-empty">{t('kb.loading')}</div>}
          {!loading && files.length === 0 && (
            <div className="kb-empty">
              {t('kb.no_knowledge')}
              <button
                className="btn btn-primary btn-sm"
                style={{ marginTop: 12 }}
                onClick={() => navigate(`/projects/${projectId}/init`)}
              >
                {t('kb.generate')}
              </button>
            </div>
          )}
          {files.map(f => {
            const labelKey = SKILL_KEYS[f.name]
            const label = labelKey ? t(labelKey) : f.name
            return (
              <div
                key={f.name}
                className={`kb-file-item ${selected === f.name ? 'active' : ''} ${!f.content ? 'empty' : ''}`}
                onClick={() => f.content && setSelected(f.name)}
              >
                <span className={`kb-file-dot ${f.content ? 'has-content' : ''}`} />
                <span className="kb-file-name">{label}</span>
                {f.type === 'index' && <span className="kb-file-badge">index</span>}
              </div>
            )
          })}
        </div>
        <div className="kb-content">
          {selectedFile?.content ? (
            <MarkdownViewer content={selectedFile.content} />
          ) : (
            <div className="kb-content-empty">
              {selected ? t('kb.empty_file') : t('kb.select_file')}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
