import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

export default function TermsPage() {
  return <PublicShell><div className="page static-page">
    <h1>使用条款</h1>
    <ol className="static-list">
      <li>CloudSite 是资源展示与访问框架，本软件本身不提供第三方资源站内容。</li>
      <li>实际资源由具体部署者配置的 Storage（如 AList 连接的网盘）提供。</li>
      <li>文件可用性受 AList / Storage Provider 影响，不保证所有资源永久可访问。</li>
      <li>不保证所有文件格式都能在线预览。</li>
      <li>版权、授权及合法性由实际站点运营者负责。</li>
      <li>使用者应遵守当地法律和上游服务条款。</li>
    </ol>
    <p className="static-note">CloudSite 是开源软件框架，使用 CloudSite 搭建的具体网站由其部署者独立运营。</p>
    <SiteFooter />
  </div></PublicShell>;
}
