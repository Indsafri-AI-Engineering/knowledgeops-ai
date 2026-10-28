export type AuthenticatedUser = {
  user_id: string;
  display_name: string;
  role: string;
  capabilities: string[];
};
