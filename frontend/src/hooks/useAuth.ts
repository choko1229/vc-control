import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from '../lib/apiClient'

export interface CurrentUser {
  id: string
  username: string
  displayName: string
  avatarUrl: string | null
}

export interface MeResponse {
  user: CurrentUser
  isOwner: boolean
  sharedGuildIds: string[]
}

export function useAuth() {
  const query = useQuery<MeResponse, ApiError>({
    queryKey: ['me'],
    queryFn: () => api.get<MeResponse>('/api/me'),
    retry: false,
  })

  return {
    user: query.data?.user ?? null,
    isOwner: query.data?.isOwner ?? false,
    sharedGuildIds: query.data?.sharedGuildIds ?? [],
    isLoading: query.isLoading,
    isAuthenticated: query.isSuccess,
    isUnauthorized: query.error instanceof ApiError && query.error.status === 401,
  }
}
