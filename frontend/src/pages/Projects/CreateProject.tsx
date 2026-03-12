import { useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import ProjectForm from './ProjectForm'
import { createProject, initProject } from '../../api'
import { useLocale } from '../../hooks/useLocale'

export default function CreateProject() {
  const navigate = useNavigate()
  const { t } = useLocale()

  const handleSave = async (data: { name: string; description: string; repos: any[]; skill_names: string[] }) => {
    const project = await createProject(data)
    await initProject(project.id)
    navigate(`/projects/${project.id}/init`)
  }

  return (
    <>
      <Topbar title={t('create_project.title')} backTo="/projects" backLabel={t('create_project.back')} />
      <div className="content">
        <ProjectForm
          onSave={handleSave}
          onCancel={() => navigate('/projects')}
          saveLabel={t('create_project.save')}
        />
      </div>
    </>
  )
}
