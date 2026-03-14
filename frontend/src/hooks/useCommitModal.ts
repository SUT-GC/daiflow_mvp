import { useState, useCallback } from 'react'
import { generateCommitMessage, submitMR } from '../api'

interface UseCommitModalOptions {
  taskId: string | undefined
  taskName?: string
  onSuccess?: () => void
}

export function useCommitModal({ taskId, taskName, onSuccess }: UseCommitModalOptions) {
  const [open, setOpen] = useState(false)
  const [commitMessage, setCommitMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [generating, setGenerating] = useState(false)

  const openModal = useCallback(async () => {
    if (!taskId) return
    setOpen(true)
    setGenerating(true)
    setCommitMessage('')
    setSubmitted(false)
    try {
      const result = await generateCommitMessage(taskId)
      setCommitMessage(result.commit_message)
    } catch {
      setCommitMessage(`feat: ${taskName || 'changes'}\n\nImplemented via DaiFlow automated workflow.`)
    } finally {
      setGenerating(false)
    }
  }, [taskId, taskName])

  const closeModal = useCallback(() => {
    if (!submitting) setOpen(false)
  }, [submitting])

  const submit = useCallback(async () => {
    if (!taskId || !commitMessage.trim()) return
    setSubmitting(true)
    try {
      await submitMR(taskId, commitMessage)
      setSubmitted(true)
      onSuccess?.()
    } catch (err) {
      alert('Error: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setSubmitting(false)
    }
  }, [taskId, commitMessage, onSuccess])

  return {
    open,
    commitMessage,
    setCommitMessage,
    submitting,
    submitted,
    generating,
    openModal,
    closeModal,
    submit,
  }
}
