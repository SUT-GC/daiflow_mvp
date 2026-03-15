import { useState } from 'react'
import { useLocale } from '../../hooks/useLocale'
import { useToast } from '../../components/Toast/ToastContext'
import './CreateProject.css'

export interface RepoEntry {
  id?: string
  git_url: string
  local_path: string
  repo_type: string
  repo_type_label: string
  description: string
}

interface ProjectFormProps {
  initialName?: string
  initialDescription?: string
  initialRepos?: RepoEntry[]
  initialSkills?: string[]
  onSave: (data: { name: string; description: string; repos: RepoEntry[]; skill_names: string[] }) => Promise<void>
  onCancel: () => void
  saveLabel?: string
}

export default function ProjectForm({
  initialName = '',
  initialDescription = '',
  initialRepos,
  initialSkills = [],
  onSave,
  onCancel,
  saveLabel,
}: ProjectFormProps) {
  const { t } = useLocale()
  const toast = useToast()
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription)
  const [repos, setRepos] = useState<RepoEntry[]>(
    initialRepos || [{ git_url: '', local_path: '', repo_type: 'frontend', repo_type_label: '', description: '' }]
  )
  const [skillInput, setSkillInput] = useState('')
  const [skills, setSkills] = useState<string[]>(initialSkills)
  const [saving, setSaving] = useState(false)

  const addRepo = () => {
    setRepos([...repos, { git_url: '', local_path: '', repo_type: 'backend', repo_type_label: '', description: '' }])
  }

  const removeRepo = (index: number) => {
    setRepos(repos.filter((_, i) => i !== index))
  }

  const updateRepo = (index: number, field: keyof RepoEntry, value: string) => {
    setRepos(repos.map((r, i) => i === index ? { ...r, [field]: value } : r))
  }

  const addSkill = () => {
    if (skillInput.trim() && !skills.includes(skillInput.trim())) {
      setSkills([...skills, skillInput.trim()])
      setSkillInput('')
    }
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave({
        name: name.trim(),
        description: description.trim(),
        repos,
        skill_names: skills,
      })
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="create-project-page">
      <div className="section-head">{t('form.basic_info')}</div>
      <div className="field">
        <label className="field-label">{t('form.project_name')}</label>
        <input className="input" placeholder={t('form.project_name_placeholder')} value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="field">
        <label className="field-label">{t('form.description')}</label>
        <textarea className="input" rows={3} placeholder={t('form.description_placeholder')} value={description} onChange={e => setDescription(e.target.value)} />
      </div>

      <div className="section-head">{t('form.code_repos')}</div>
      {repos.map((repo, i) => (
        <div key={i} className="repo-block">
          <div className="repo-block-head">
            <div className="type-toggle">
              {['frontend', 'backend', 'fullstack', 'custom'].map(tp => (
                <button
                  key={tp}
                  className={`type-btn ${repo.repo_type === tp ? (tp === 'frontend' ? 'fe' : tp === 'backend' ? 'be' : tp === 'fullstack' ? 'fs' : 'custom') : ''}`}
                  onClick={() => updateRepo(i, 'repo_type', tp)}
                >
                  {tp}
                </button>
              ))}
            </div>
            {repos.length > 1 && (
              <button className="btn btn-danger btn-xs" onClick={() => removeRepo(i)}>{t('form.remove')}</button>
            )}
          </div>
          <div className="field-row">
            <div className="field">
              <label className="field-label">{t('form.git_url')}</label>
              <input className="input" placeholder="https://git.example.com/repo.git" value={repo.git_url} onChange={e => updateRepo(i, 'git_url', e.target.value)} />
            </div>
            <div className="field">
              <label className="field-label">{t('form.local_path')}</label>
              <input className="input" placeholder="/path/to/local/repo" value={repo.local_path} onChange={e => updateRepo(i, 'local_path', e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label className="field-label">{t('form.repo_desc')}</label>
            <input className="input" placeholder={t('form.repo_desc_placeholder')} value={repo.description} onChange={e => updateRepo(i, 'description', e.target.value)} />
          </div>
        </div>
      ))}
      <button className="add-repo-btn" onClick={addRepo}>{t('form.add_repo')}</button>

      <div className="section-head" style={{ marginTop: 28 }}>{t('form.skill_config')}</div>
      <div className="field">
        <label className="field-label">{t('form.skill_names')}</label>
        <input
          className="input"
          placeholder={t('form.skill_placeholder')}
          value={skillInput}
          onChange={e => setSkillInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSkill() } }}
        />
      </div>
      {skills.length > 0 && (
        <div className="skill-pills">
          {skills.map((s, i) => (
            <span key={i} className="tag tag-purple">
              {s}
              <span style={{ cursor: 'pointer', marginLeft: 6 }} onClick={() => setSkills(skills.filter((_, j) => j !== i))}>x</span>
            </span>
          ))}
        </div>
      )}

      <div className="form-footer">
        <button className="btn btn-ghost" onClick={onCancel}>{t('form.cancel')}</button>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving || !name.trim()}>
          {saving ? t('form.saving') : (saveLabel || t('form.save'))}
        </button>
      </div>
    </div>
  )
}
