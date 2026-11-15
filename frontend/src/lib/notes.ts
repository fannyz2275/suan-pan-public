import api from './api'

export interface UserNote {
  id: string
  kind: 'fact' | 'preference'
  content: string
  tags: string[]
  importance: number
  strength: number
  created_at: string
}

export async function fetchUserNotes(): Promise<UserNote[]> {
  const { data } = await api.get<UserNote[]>('/notes/user')
  return data
}

export async function forgetNote(id: string): Promise<void> {
  await api.delete(`/notes/user/${id}`)
}
