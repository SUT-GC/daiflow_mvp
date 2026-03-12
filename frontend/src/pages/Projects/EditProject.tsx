import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import Loading from '../../components/Loading/Loading'
import ProjectForm from './ProjectForm'
import type { RepoEntry } from './ProjectForm'
import { getProject, updateProject } from '../../api'
import { useLocale } from '../../hooks/useLocale'

export default function EditProject() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [loading, setLoading] = useState(true)
  const [initialData, setInitialData] = useState<{
    name: string; description: string; repos: RepoEntry[]; skills: string[]
  } | null>(null)

  useEffect(() => {
    if (!projectId) return
    getProject(projectId).then(p => {
      setInitialData({
        name: p.name || '',
        description: p.description || '',
        repos: p.repos || [],
        skills: p.skill_names || [],
      })
    }).catch(() => {}).finally(() => setLoading(false))
  }, [projectId])

  if (loading || !initialData) return <Loading />

  const handleSave = async (data: { name: string; description: string; repos: any[]; skill_names: string[] }) => {
    if (!projectId) return
    await updateProject(projectId, data)
    navigate('/projects')
  }

  return (
    <>
      <Topbar title={t('edit_project.title')} backTo="/projects" backLabel={t('edit_project.back')} />
      <div className="content">
        <ProjectForm
          initialName={initialData.name}
          initialDescription={initialData.description}
          initialRepos={initialData.repos}
          initialSkills={initialData.skills}
          onSave={handleSave}
          onCancel={() => navigate('/projects')}
          saveLabel={t('edit_project.save')}
        />
      </div>
    </>
  )
}
