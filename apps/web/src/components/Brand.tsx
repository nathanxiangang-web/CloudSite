import { Cloud } from "lucide-react";
import Link from "next/link";

export function Brand({ admin = false, name = "CloudSite" }: { admin?: boolean; name?: string }) {
  return <Link href={admin ? "/admin" : "/"} className="brand"><span className="brand-icon"><Cloud size={22} strokeWidth={2.6} /></span><strong>{name}</strong>{admin && <span>Admin</span>}</Link>;
}
