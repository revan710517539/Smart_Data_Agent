export function canDeleteSharedVisual(args: {
  isSuperAdmin: boolean;
  isInstitutionAdmin: boolean;
  ownerUserId?: string;
  userId: string;
}): boolean {
  const owner = String(args.ownerUserId || "").trim();
  if (owner && owner === args.userId) return true;
  return args.isSuperAdmin || args.isInstitutionAdmin;
}

export function canDeleteOwnVisualCopy(args: { createdByUserId?: string; userId: string; isSuperAdmin?: boolean }): boolean {
  const owner = String(args.createdByUserId || "").trim();
  if (!owner) return Boolean(args.isSuperAdmin);
  return owner === args.userId || Boolean(args.isSuperAdmin);
}
