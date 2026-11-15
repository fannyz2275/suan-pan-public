import { createContext, useContext } from 'react'

export interface ToastState {
  message: string
  transferCount: number
  onReview?: () => void
}

interface ToastApi {
  showImportToast: (state: ToastState) => void
}

export const ImportToastContext = createContext<ToastApi | null>(null)

export function useImportToast(): ToastApi {
  const value = useContext(ImportToastContext)
  if (!value) throw new Error('useImportToast must be inside ImportToastProvider')
  return value
}
