"use client";

import { Cloud } from "lucide-react";
import Link from "next/link";
import { useSite } from "@/lib/site";

export function Brand({ admin = false, name }: { admin?: boolean; name?: string }) {
  const site = useSite();
  return <Link href={admin ? "/admin" : "/"} className="brand"><span className="brand-icon"><Cloud size={22} strokeWidth={2.6} /></span><strong>{name || site.site_name}</strong>{admin && <span>Admin</span>}</Link>;
}
