export interface AuthUser {
  id: string;
  display_name?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
}

export interface AuthMeResponse {
  user: AuthUser;
}
